import json
import sys
import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from memoryos.memory_store import MemoryStore
from services.feishu import FeishuConfig,FeishuConnectorService,FakeFeishuClient
from services.feishu.connector_service import parse_message_event,_extract_actual_approvers
from services.feishu.feishu_client import FeishuClientError,NETWORK


class FeishuIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=MemoryStore(str(Path(self.tmp.name)/'db.sqlite'))
        self.cfg=FeishuConfig(app_id='fixture',app_secret='fixture',tenant_id='t',allowed_chat_ids=['chat'],approver_open_ids=['ou_a'],approval_definition_code='definition',approval_form_control_id='real_control',approval_initiator_open_id='ou_i',live=True)
        self.client=FakeFeishuClient(self.cfg);self.service=FeishuConnectorService(self.store,self.client,self.cfg)

    def approval(self,kind='text'):
        summary=self.service.document_draft('Document','结论：验证新架构\n行动项：核对证据','document:1#version=3')
        a=self.service.create_approval(summary['id'],'chat','chat',confirmed=True,outbound_msg_type=kind)
        self.client.approve(a['feishu_instance_code']);self.service.sync_approval(a['id'])
        return a

    def test_real_event_sender_and_received_post_rows(self):
        event=dict(header=dict(event_id='e',tenant_key='t',app_id='fixture'),event=dict(sender=dict(sender_id=dict(open_id='actual')),message=dict(message_id='m',chat_id='chat',message_type='post',content=json.dumps(dict(title='Post',content=[[dict(tag='text',text='one'),dict(tag='a',text='two',href='https://example.com')],[dict(tag='text',text='three')]])))))
        p=parse_message_event(event);self.assertEqual(p['sender_id'],'actual');self.assertEqual(p['text'],'one\ntwo\nthree')
        self.assertEqual(self.service.receive_event(event)['sender_id'],'actual')
        event['header']['tenant_key']='foreign'
        with self.assertRaises(PermissionError):self.service.receive_event(event)

    def test_only_decided_approvers_count_not_pending_missing_or_arbitrary_timeline(self):
        self.assertEqual(_extract_actual_approvers(dict(task_list=[dict(open_id='ou_a'),dict(open_id='ou_a',status='PENDING')],timeline=[dict(open_id='ou_a'),dict(open_id='ou_a',type='START')])),[])
        self.assertEqual(_extract_actual_approvers(dict(task_list=[dict(open_id='ou_a',status='APPROVED')],timeline=[])),['ou_a'])

    def test_frozen_body_contains_document_and_only_real_form_control(self):
        a=self.approval();self.assertIn('验证新架构',a['body_text'])
        form=self.client.approval_meta[a['feishu_instance_code']]['form']
        self.assertEqual([f['id'] for f in form],['real_control'])
        self.assertIn(a['content_hash'],form[0]['value']);self.assertIn('document:1#version=3',form[0]['value'])

    def test_current_approval_query_failure_blocks_cached_approval(self):
        a=self.approval()
        with patch.object(self.client,'get_approval_instance',side_effect=FeishuClientError('offline',category=NETWORK)):
            with self.assertRaises(PermissionError):self.service.send_after_approval(a['id'],confirmed=True)
        self.assertEqual(self.client.send_calls,[])

    def test_changed_native_approval_blocks_and_post_message_is_correctly_shaped(self):
        a=self.approval();self.client.reject(a['feishu_instance_code'])
        with self.assertRaises(PermissionError):self.service.send_after_approval(a['id'],confirmed=True)
        b=self.approval('post');sent=self.service.send_after_approval(b['id'],confirmed=True)
        self.assertEqual(sent['status'],'sent');payload=json.loads(self.client.send_calls[0]['content']);self.assertIn('验证新架构',payload['zh_cn']['content'][0][0]['text'])

    def test_other_tenant_cannot_list_mutate_or_approve_resources(self):
        a=self.approval();other=FeishuConnectorService(self.store,None,FeishuConfig(tenant_id='other'))
        self.assertEqual(other.list_summaries(),[]);self.assertEqual(other.list_approvals(),[])
        with self.assertRaises(ValueError):other.get_approval(a['id'])
        with self.assertRaises(ValueError):other.update_summary(a['summary_id'],dict(topic='overwrite'))
        self.assertNotEqual(self.service.get_summary(a['summary_id'])['topic'],'overwrite')

    def test_live_mode_incomplete_config_cannot_silently_dry_run(self):
        bad=FeishuConnectorService(self.store,None,FeishuConfig(tenant_id='t',live=True,allowed_chat_ids=['chat']))
        summary=bad.document_draft('t','body','source')
        with self.assertRaises(RuntimeError):bad.create_approval(summary['id'],'chat','chat',confirmed=True)
        a=self.approval()
        with self.assertRaises(RuntimeError):bad.send_after_approval(a['id'],confirmed=True)
        self.assertEqual(self.client.send_calls,[])

    def test_parallel_delivery_calls_at_most_once(self):
        a=self.approval()
        def send():
            try:return self.service.send_after_approval(a['id'],confirmed=True)['status']
            except PermissionError:return 'already_used'
        with ThreadPoolExecutor(4) as pool:results=list(pool.map(lambda _:send(),range(4)))
        self.assertEqual(len(self.client.send_calls),1);self.assertTrue(all(x in ('sent','sending','already_used') for x in results))

if __name__=='__main__':unittest.main()
