"""Synthetic infrastructure fixtures; these are not real learning-effect results."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from memoryos.memory_store import MemoryStore
from services.academy_materials import AcademyMaterials
from services.academy_learning_lab import AcademyLearningLab
from services.academy_lab_api import lab_router,strict_reply
from services.textbook_learning_graph import book_index
from services.academy_teaching_quality import DIMS


class EducationLabTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.m=AcademyMaterials(MemoryStore(str(Path(self.tmp.name)/'db')),Path(self.tmp.name)/'materials')
        result=self.m.upload('book.md',b'# Evidence\nEvidence supports conclusions.\n# Conditions\nMissing evidence requires refusal.')
        self.mid=result['document']['id'];self.chapters=result['chapters'];self.now=[1000000.]
        self.lab=AcademyLearningLab(self.m,clock=lambda:self.now[0]);self.g=self.lab.graph.state(self.mid,'local-user')
        self.calls=[];self.provider_hook=None
        async def model(messages,tools):
            self.calls.append(messages)
            if self.provider_hook:self.provider_hook()
            return {'choices':[{'message':{'content':json.dumps(self.proposal)}}]}
        app=FastAPI();app.include_router(lab_router(lambda:self.lab,model))
        self.client=TestClient(app,client=('127.0.0.1',4455));self.addCleanup(self.client.close)
        self.teacher,self.ttoken=self.join('teacher');self.teacher2,self.t2token=self.join('teacher');self.student,self.stoken=self.join('learner')

    def join(self,role):
        invitation=self.lab.invite(self.mid,'local-user',role)
        result,token=self.lab.join(invitation['code'],'Synthetic '+role)
        return result['user_id'],token

    def graph_value(self):
        source=self.m.document(self.mid)['payload']['passages'][0]
        chapters=self.g['index']['chapters']
        return dict(nodes=[dict(id='a',title='Evidence',chapter=chapters[0]['id'],explanation='Evidence supports conclusions.',source=dict(citation=source['id'],quote='Evidence supports conclusions.')),
                           dict(id='b',title='Conditions',chapter=chapters[1]['id'],explanation='Missing evidence requires refusal.',source=dict(citation=source['id'],quote='Missing evidence requires refusal.'))],
                    edges=[dict(**{'from':'a','to':'b'},kind='prerequisite',status='proposed',reason='Synthetic relation to exercise manual review.',source=dict(citation=source['id'],quote='Missing evidence requires refusal.'))],covered_chapters=[c['id'] for c in chapters])

    def save_graph(self,value=None,version=0):return self.lab.graph.save(self.mid,'local-user',value or self.graph_value(),version,self.g['revision'])

    def protocol(self):
        return dict(title='Synthetic observational infrastructure test',chapter=self.chapters[0]['id'],delay_days=7,min_pairs=12,
                    forms=[[dict(dimension=d,question=f'Explain evidence condition, form {f} dimension {d}.',criterion='Explain mechanism and missing-evidence boundary.',quote='Evidence supports conclusions.',reference_answer='Evidence supports conclusions under stated conditions.') for d in DIMS] for f in range(3)])

    def create_study(self):return self.lab.evidence.create(self.mid,'local-user',self.protocol(),self.g['revision'],0)['id']

    def headers(self,token):return {'Authorization':'Bearer '+token}

    def test_chunk_continuation_and_overlap_keep_original_spans(self):
        quote='A continuous source sentence. '
        doc=dict(payload=dict(revision='r',passages=[dict(id='p1',text='# Chapter A\n'+quote*4,source_url='/1'),dict(id='p2',text=quote*2+'More detail.\n# Chapter B\nOther detail.',source_url='/2')]))
        index=book_index(doc);self.assertEqual(len(index['chapters']),2)
        self.assertEqual(len(index['chapters'][0]['sources']),2)
        self.assertGreater(index['chapters'][0]['sources'][1]['start'],0)
        for ch in index['chapters']:
            for span in ch['sources']:self.assertLessEqual(span['end'],len(next(p for p in doc['payload']['passages'] if p['id']==span['citation'])['text']))

    def test_manual_confirmation_controls_route(self):
        g=self.save_graph();self.assertEqual([n['id'] for n in self.lab.graph.route(self.mid,self.student,'b')['nodes']],['b'])
        value=self.graph_value();value['edges'][0]['status']='confirmed';self.save_graph(value,1)
        self.assertEqual([n['id'] for n in self.lab.graph.route(self.mid,self.student,'b')['nodes']],['a','b'])

    def test_cycle_source_and_cas_rejected(self):
        value=self.graph_value();value['edges'][0]['status']='confirmed'
        reverse=dict(value['edges'][0],**{'from':'b','to':'a'});value['edges'].append(reverse)
        with self.assertRaisesRegex(ValueError,'环'):self.save_graph(value)
        value=self.graph_value();value['nodes'][0]['source']['quote']='Fabricated citation'
        with self.assertRaisesRegex(ValueError,'引用'):self.save_graph(value)
        self.save_graph()
        with self.assertRaisesRegex(ValueError,'冲突'):self.save_graph()

    def test_invitation_single_use_and_scoped_revoke(self):
        invitation=self.lab.invite(self.mid,'local-user','learner');joined,_=self.lab.join(invitation['code'],'Synthetic')
        with self.assertRaises(ValueError):self.lab.join(invitation['code'],'Again')
        self.assertEqual(len(self.lab.books(joined['user_id'])),1)
        self.lab.revoke(self.mid,'local-user',joined['user_id'])
        with self.assertRaises(HTTPException):self.lab.state(self.mid,joined['user_id'])
        with self.assertRaises(HTTPException):self.lab.invite(self.mid,self.student,'teacher')

    def test_learner_no_teacher_labels_or_other_book(self):
        state=self.lab.state(self.mid,self.student)
        self.assertNotIn('teacher_draft',state);self.assertNotIn('calibration',state);self.assertNotIn('chapters',state)
        other=self.m.upload('other.md',b'# Private\nPrivate source belongs to another book.')['document']['id']
        response=self.client.get('/api/academy/learning/lab/books/'+other,headers=self.headers(self.stoken))
        self.assertEqual(response.status_code,403)
        response=self.client.post('/api/academy/learning/lab/books/'+self.mid+'/invite',json={'role':'teacher','user_id':'local-user'},headers=self.headers(self.stoken))
        self.assertEqual(response.status_code,403)

    def test_model_batch_cannot_confirm_or_cover_unseen_chapter(self):
        g,messages=self.lab.graph.prompt(self.mid,'local-user',[self.g['index']['chapters'][0]['id']])
        proposal=self.graph_value()
        with self.assertRaisesRegex(ValueError,'未提供'):self.lab.graph.merge_proposal(self.mid,'local-user',g,proposal)
        g,_=self.lab.graph.prompt(self.mid,'local-user',[c['id'] for c in self.g['index']['chapters']])
        proposal['edges'][0]['status']='confirmed'
        saved=self.lab.graph.merge_proposal(self.mid,'local-user',g,proposal)
        self.assertEqual(saved['edges'][0]['status'],'proposed')

    def test_graph_api_failure_and_actual_run_receipt(self):
        self.proposal=self.graph_value()
        response=self.client.post('/api/academy/learning/lab/books/'+self.mid+'/graph-propose',json={'chapters':[c['id'] for c in self.g['index']['chapters']]})
        self.assertEqual(response.status_code,200,response.text);self.assertEqual(len(self.calls),1)
        self.assertTrue(response.json()['run_id'].startswith('academy-lab-'))
        self.assertEqual(response.json()['result']['edges'][0]['status'],'proposed')

    def test_strict_json_rejects_duplicate_and_nonfinite(self):
        for raw in ('{"nodes":[],"nodes":[]}','{"value":NaN}','[]'):
            with self.assertRaises(ValueError):strict_reply({'choices':[{'message':{'content':raw}}]})

    def test_protocol_requires_unique_parallel_forms_and_source(self):
        for kind in ('duplicate','citation','delay'):
            p=self.protocol()
            if kind=='duplicate':p['forms'][1][0]['question']=p['forms'][0][0]['question']
            if kind=='citation':p['forms'][0][0]['quote']='Invented quotation'
            if kind=='delay':p['delay_days']=1
            with self.assertRaises(ValueError):self.lab.evidence.create(self.mid,'local-user',p,self.g['revision'],0)

    def test_source_and_graph_drift_block_active_study(self):
        sid=self.create_study();self.lab.evidence.enroll(sid,self.student);self.save_graph()
        self.assertTrue(self.lab.evidence.view(sid,self.student)['stale'])
        with self.assertRaisesRegex(ValueError,'变化'):self.lab.evidence.answer(sid,self.student,'pre',['Synthetic response.']*3)
        self.assertEqual(self.lab.evidence.report(sid,self.teacher)['status'],'stale')

    def test_frozen_attempts_delay_gate_and_no_answer_key(self):
        sid=self.create_study();view=self.lab.evidence.enroll(sid,self.student)
        for q in view['questions']:self.assertEqual(set(q),{'question','dimension'})
        self.lab.evidence.answer(sid,self.student,'pre',['Synthetic student answer.']*3)
        with self.assertRaises(ValueError):self.lab.evidence.answer(sid,self.student,'pre',['Replacement answer.']*3)
        with self.assertRaises(ValueError):self.lab.evidence.answer(sid,self.student,'post',['Synthetic student answer.']*3,'Synthetic learning journal.')
        self.now[0]+=600
        self.lab.evidence.answer(sid,self.student,'post',['Synthetic student answer.']*3,'Synthetic journal, not an actual learner.')
        self.now[0]+=7*86400-1
        with self.assertRaises(ValueError):self.lab.evidence.answer(sid,self.student,'delayed',['Synthetic student answer.']*3)
        self.now[0]+=1
        self.lab.evidence.answer(sid,self.student,'delayed',['Synthetic student answer.']*3)
        self.assertIsNone(self.lab.evidence.view(sid,self.student)['next_phase'])

    def test_blind_packets_exclude_phase_identity_and_own_answers(self):
        sid=self.create_study();self.lab.evidence.enroll(sid,self.student);self.lab.evidence.answer(sid,self.student,'pre',['Synthetic student answer.']*3)
        packet=self.lab.evidence.packets(sid,self.teacher)[0]
        self.assertFalse(set(packet)&{'phase','user_id','created','name','prior_grades'})
        self.assertNotIn(self.student,json.dumps(packet))
        self.lab.evidence.enroll(sid,'local-user');self.lab.evidence.answer(sid,'local-user','pre',['Synthetic owner answer.']*3)
        self.assertEqual(len(self.lab.evidence.packets(sid,'local-user')),1)
        with self.assertRaises(HTTPException):self.lab.evidence.packets(sid,self.student)

    def test_two_raters_dispute_and_immutable_grade(self):
        sid=self.create_study();self.lab.evidence.enroll(sid,self.student);self.lab.evidence.answer(sid,self.student,'pre',['Synthetic student answer.']*3)
        aid=self.lab.evidence.packets(sid,self.teacher)[0]['packet_id']
        self.lab.evidence.grade(sid,self.teacher,aid,{d:1 for d in DIMS},'Synthetic test reason only.',['Synthetic student answer.']*3)
        with self.assertRaisesRegex(ValueError,'覆盖'):self.lab.evidence.grade(sid,self.teacher,aid,{d:1 for d in DIMS},'Synthetic test reason only.',['Synthetic student answer.']*3)
        self.lab.evidence.grade(sid,self.teacher2,aid,{d:2 for d in DIMS},'Synthetic different score only.',['Synthetic student answer.']*3)
        report=self.lab.evidence.report(sid,self.teacher);self.assertEqual(report['disputed_attempts'],1);self.assertEqual(report['complete_paired_accounts'],0)

    def test_synthetic_complete_record_never_proves_real_or_causal_effect(self):
        sid=self.create_study();self.lab.evidence.enroll(sid,self.student)
        for phase in ('pre','post','delayed'):
            self.lab.evidence.answer(sid,self.student,phase,['Synthetic student answer.']*3,'Synthetic learning journal only.')
            for teacher in (self.teacher,self.teacher2):
                packet=self.lab.evidence.packets(sid,teacher)[0]
                self.lab.evidence.grade(sid,teacher,packet['packet_id'],{d:1 if phase=='pre' else 2 for d in DIMS},'Synthetic label for mechanism verification.',['Synthetic student answer.']*3)
            self.now[0]+=600 if phase=='pre' else 7*86400
        report=self.lab.evidence.report(sid,self.teacher)
        self.assertEqual(report['complete_paired_accounts'],1);self.assertEqual(report['post_gain']['mean'],3)
        self.assertFalse(report['real_learning_effect_verified']);self.assertFalse(report['causal_effect_verified']);self.assertFalse(report['identity_independence_verified'])
        self.assertEqual(report['status'],'collecting')

    def test_revoked_teacher_cannot_read_or_submit_blind_grade(self):
        sid=self.create_study();self.lab.evidence.enroll(sid,self.student);self.lab.evidence.answer(sid,self.student,'pre',['Synthetic student answer.']*3)
        aid=self.lab.evidence.packets(sid,self.teacher)[0]['packet_id'];self.lab.revoke(self.mid,'local-user',self.teacher)
        with self.assertRaises(HTTPException):self.lab.evidence.grade(sid,self.teacher,aid,{d:2 for d in DIMS},'Synthetic grade should be rejected.',['Synthetic student answer.']*3)

    def test_csrf_and_invalid_payload_rejected(self):
        response=self.client.post('/api/academy/learning/lab/join',json={'code':'x'*32,'name':'Synthetic'},headers={'Origin':'https://evil.invalid'})
        self.assertEqual(response.status_code,403)
        response=self.client.post('/api/academy/learning/lab/books/'+self.mid+'/graph',json=[])
        self.assertEqual(response.status_code,400)

    def test_empty_report_is_honest_and_missing_counts_kept(self):
        sid=self.create_study();self.lab.evidence.enroll(sid,self.student)
        report=self.lab.evidence.report(sid,self.teacher)
        self.assertEqual(report['enrolled'],1);self.assertEqual(report['missing'],{d:1 for d in ('pre','post','delayed')});self.assertIsNone(report['post_gain']['mean'])

    def test_teacher_draft_version_conflict_and_freeze_invalid_bank(self):
        draft=self.lab.draft(self.mid,self.teacher)
        self.lab.save_draft(self.mid,self.teacher,dict(cases=[]),draft['version'],draft['revision'])
        with self.assertRaisesRegex(ValueError,'冲突'):self.lab.save_draft(self.mid,self.teacher,dict(cases=[]),0,draft['revision'])
        with self.assertRaises(ValueError):self.lab.freeze_bank(self.mid,self.teacher,1)

    def test_manual_directory_partitions_all_source_and_invalidates_graph(self):
        saved=self.save_graph();passage=self.m.document(self.mid)['payload']['passages'][0]
        starts=[dict(citation=passage['id'],offset=0,title='First chapter'),dict(citation=passage['id'],offset=passage['text'].index('# Conditions'),title='Second chapter')]
        graph=self.lab.save_index(self.mid,self.teacher,starts,0,self.g['revision'])
        self.assertEqual(graph['version'],saved['version']+1);self.assertEqual(graph['nodes'],[])
        chapters=graph['index']['chapters'];self.assertTrue(graph['index']['manual'])
        self.assertEqual(chapters[0]['sources'][0]['end'],chapters[1]['sources'][0]['start'])
        self.assertEqual(chapters[-1]['sources'][-1]['end'],len(passage['text']))
        with self.assertRaisesRegex(ValueError,'冲突'):self.lab.save_index(self.mid,self.teacher,starts,0,self.g['revision'])

    def test_directory_rejects_gaps_wrong_order_and_unauthorized_edits(self):
        passage=self.m.document(self.mid)['payload']['passages'][0]
        for starts in ([dict(citation=passage['id'],offset=1,title='Missing beginning')],
                       [dict(citation=passage['id'],offset=0,title='First'),dict(citation=passage['id'],offset=0,title='Duplicate')]):
            with self.assertRaises(ValueError):self.lab.save_index(self.mid,self.teacher,starts,0,self.g['revision'])
        with self.assertRaises(HTTPException):self.lab.save_index(self.mid,self.student,[dict(citation=passage['id'],offset=0,title='First')],0,self.g['revision'])

    def test_valid_teacher_bank_freeze_records_authenticated_actor(self):
        chapter=self.chapters[0]
        value=dict(teacher='Synthetic Fixture Teacher',reviewed_at='2026-01-01',human_reviewed=True,cases=[dict(id=str(i),split='anchor' if i<3 else 'holdout',chapter=chapter['id'],questions=[dict(dimension=d,question='Explain evidence condition.',criterion='Explain mechanism and condition.',quote='Evidence supports conclusions.') for d in DIMS],answers=['Synthetic unique response '+str(i)]*3,scores={d:i%3 for d in DIMS},reason='Synthetic label for infrastructure tests only.') for i in range(9)])
        self.lab.save_draft(self.mid,self.teacher,value,0,self.g['revision'])
        result=self.lab.freeze_bank(self.mid,self.teacher,1)
        with self.lab.store._conn() as c:
            stored=json.loads(c.execute('SELECT payload FROM academy_material_events WHERE id=?',(result['event_id'],)).fetchone()['payload'])
        self.assertEqual(stored['authenticated_actor'],self.teacher);self.assertFalse(stored['teacher_qualification_verified'])
        self.assertNotIn('calibration',self.lab.state(self.mid,self.student))

    def test_revocation_during_model_call_rejects_persistence(self):
        self.proposal=self.graph_value()
        self.provider_hook=lambda:self.lab.revoke(self.mid,'local-user',self.teacher)
        response=self.client.post('/api/academy/learning/lab/books/'+self.mid+'/graph-propose',json={'chapters':[c['id'] for c in self.g['index']['chapters']]},headers=self.headers(self.ttoken))
        self.assertEqual(response.status_code,403)
        self.assertEqual(self.lab.graph.state(self.mid,'local-user')['nodes'],[])

    def test_existing_identity_can_join_another_book_without_losing_records(self):
        other=self.m.upload('second.md',b'# Second\nA different source in another book.')['document']['id']
        code=self.lab.invite(other,'local-user','learner')['code']
        joined,_=self.lab.join(code,'Name does not replace identity',self.student)
        self.assertEqual(joined['user_id'],self.student);self.assertEqual(len(self.lab.books(self.student)),2)

    def test_explicit_withdrawal_preserves_counts_and_prevents_new_answers(self):
        sid=self.create_study();self.lab.evidence.enroll(sid,self.student)
        self.lab.evidence.answer(sid,self.student,'pre',['Synthetic student answer.']*3)
        view=self.lab.evidence.withdraw(sid,self.student,'Synthetic withdrawal reason only.')
        self.assertTrue(view['withdrawn']);self.assertEqual(len(view['attempts']),1)
        self.now[0]+=600
        with self.assertRaises(ValueError):self.lab.evidence.answer(sid,self.student,'post',['Synthetic student answer.']*3,'Synthetic learning journal.')
        report=self.lab.evidence.report(sid,self.teacher)
        self.assertEqual(report['withdrawn_accounts'],1);self.assertEqual(report['enrolled'],1);self.assertEqual(report['submitted']['pre'],1)

    def test_teaching_uses_same_whole_book_directory_as_graph(self):
        passage=self.m.document(self.mid)['payload']['passages'][0]
        self.lab.save_index(self.mid,self.teacher,[dict(citation=passage['id'],offset=0,title='A full merged chapter')],0,self.g['revision'])
        state=self.lab.state(self.mid,self.teacher)
        self.assertEqual(len(state['chapters']),1)
        chapter=state['chapters'][0];self.assertEqual(chapter['id'],'book:ch0001')
        self.assertIn('Missing evidence requires refusal.',chapter['text'])
        protocol=self.protocol();protocol['chapter']=chapter['id']
        sid=self.lab.evidence.create(self.mid,self.teacher,protocol,self.g['revision'],1)['id']
        self.assertEqual(self.lab.evidence.view(sid,self.student)['chapter'],chapter['id'])

    def test_directory_change_invalidates_draft_and_whole_chapter_bank(self):
        from services.academy_teaching_quality import AcademyTeachingQuality
        self.test_valid_teacher_bank_freeze_records_authenticated_actor()
        value=self.lab.draft(self.mid,self.teacher)['value']
        for case in value['cases']:case['chapter']='book:ch0001'
        self.lab.save_draft(self.mid,self.teacher,value,1,self.g['revision']);self.lab.freeze_bank(self.mid,self.teacher,2)
        quality=AcademyTeachingQuality(self.m)
        self.assertIsNotNone(quality.bank(self.mid))
        passage=self.m.document(self.mid)['payload']['passages'][0]
        self.lab.save_index(self.mid,self.teacher,[dict(citation=passage['id'],offset=0,title='Merged chapter')],0,self.g['revision'])
        self.assertIsNone(quality.bank(self.mid));self.assertTrue(self.lab.draft(self.mid,self.teacher)['stale'])
        with self.assertRaises(ValueError):self.lab.freeze_bank(self.mid,self.teacher,2)

    def test_dispute_adjudication_requires_new_rater_and_freezes_final_score(self):
        sid=self.create_study();self.lab.evidence.enroll(sid,self.student);self.lab.evidence.answer(sid,self.student,'pre',['Synthetic student answer.']*3)
        aid=self.lab.evidence.packets(sid,self.teacher)[0]['packet_id']
        for teacher,score in ((self.teacher,1),(self.teacher2,2)):
            self.lab.evidence.grade(sid,teacher,aid,{d:score for d in DIMS},'Synthetic disagreement, not human data.',['Synthetic student answer.']*3)
        with self.assertRaises(ValueError):self.lab.evidence.grade(sid,self.teacher,aid,{d:2 for d in DIMS},'Same rater cannot adjudicate.',['Synthetic student answer.']*3,adjudication=True)
        packet=self.lab.evidence.packets(sid,'local-user',adjudication=True)[0]
        self.assertEqual(len(packet['disputed_grades']),2);self.assertNotIn('phase',packet)
        self.lab.evidence.grade(sid,'local-user',aid,{d:1 for d in DIMS},'Synthetic third account adjudication.',['Synthetic student answer.']*3,adjudication=True)
        report=self.lab.evidence.report(sid,self.teacher)
        self.assertEqual(report['disputed_attempts'],1);self.assertEqual(report['adjudicated_attempts'],1);self.assertEqual(report['unresolved_disputes'],0)
        self.assertEqual(self.lab.evidence.packets(sid,'local-user',adjudication=True),[])
        another,_=self.join('teacher')
        with self.assertRaisesRegex(ValueError,'冻结'):self.lab.evidence.grade(sid,another,aid,{d:2 for d in DIMS},'No changes after arbitration.',['Synthetic student answer.']*3)

    def test_agreed_or_unrated_attempt_cannot_be_adjudicated(self):
        sid=self.create_study();self.lab.evidence.enroll(sid,self.student);self.lab.evidence.answer(sid,self.student,'pre',['Synthetic student answer.']*3)
        aid=self.lab.evidence.packets(sid,self.teacher)[0]['packet_id']
        for stage in range(3):
            with self.assertRaisesRegex(ValueError,'分歧'):self.lab.evidence.grade(sid,'local-user',aid,{d:2 for d in DIMS},'Synthetic arbitration must be rejected.',['Synthetic student answer.']*3,adjudication=True)
            if stage<2:self.lab.evidence.grade(sid,(self.teacher,self.teacher2)[stage],aid,{d:2 for d in DIMS},'Synthetic agreed teacher scores.',['Synthetic student answer.']*3)

    def test_expired_session_renewal_keeps_original_learner_attempts(self):
        sid=self.create_study();self.lab.evidence.enroll(sid,self.student);self.lab.evidence.answer(sid,self.student,'pre',['Synthetic answer before expiry.']*3)
        renewal=self.lab.invite(self.mid,'local-user','learner',self.student)
        with self.lab.store._conn() as c:c.execute('UPDATE collaboration_sessions SET expires=0 WHERE user_id=?',(self.student,))
        response=self.client.post('/api/academy/learning/lab/logout',json={},headers=self.headers(self.stoken))
        self.assertEqual(response.status_code,200)
        renewed,_=self.lab.join(renewal['code'],'Does not replace original name')
        self.assertEqual(renewed['user_id'],self.student)
        view=self.lab.evidence.view(sid,self.student)
        self.assertEqual(len(view['attempts']),1);self.assertEqual(view['next_phase'],'post')

    def test_bound_renewal_cannot_switch_person_or_restore_revoked_grant(self):
        renewal=self.lab.invite(self.mid,'local-user','learner',self.student)
        with self.assertRaisesRegex(ValueError,'绑定'):self.lab.join(renewal['code'],'Synthetic',self.teacher)
        self.lab.revoke(self.mid,'local-user',self.student)
        with self.assertRaisesRegex(ValueError,'撤销'):self.lab.join(renewal['code'],'Synthetic')
        with self.assertRaises(ValueError):self.lab.invite(self.mid,'local-user','teacher',self.student)

    def test_frozen_protocol_preserves_actual_graph_directory_and_source(self):
        self.save_graph()
        sid=self.lab.evidence.create(self.mid,self.teacher,self.protocol(),self.g['revision'],1)['id']
        frozen=self.lab.evidence.protocol(sid,self.teacher)['protocol']
        self.assertEqual(frozen['graph_snapshot']['nodes'][0]['title'],'Evidence')
        self.assertIn('Evidence supports conclusions.',frozen['chapter_snapshot']['text'])
        self.assertEqual(len(frozen['directory_snapshot']['chapters']),2)
        changed=self.graph_value();changed['nodes'][0]['title']='Edited later'
        self.save_graph(changed,1)
        after=self.lab.evidence.protocol(sid,self.teacher)
        self.assertTrue(after['stale']);self.assertEqual(after['protocol'],frozen)
        with self.assertRaises(HTTPException):self.lab.evidence.protocol(sid,self.student)

    def test_replaced_graph_and_directory_versions_remain_auditable(self):
        self.save_graph();changed=self.graph_value();changed['nodes'][0]['title']='Edited later';self.save_graph(changed,1)
        passage=self.m.document(self.mid)['payload']['passages'][0]
        self.lab.save_index(self.mid,self.teacher,[dict(citation=passage['id'],offset=0,title='Merged chapter')],0,self.g['revision'])
        history=self.lab.history(self.mid,self.teacher)
        self.assertEqual([g['version'] for g in history['graphs']],[1,2,3])
        self.assertEqual(history['graphs'][0]['graph']['nodes'][0]['title'],'Evidence')
        self.assertEqual(history['graphs'][1]['graph']['nodes'][0]['title'],'Edited later')
        self.assertEqual(history['graphs'][2]['graph']['nodes'],[])
        self.assertEqual(history['directories'][0]['version'],1)
        with self.assertRaises(HTTPException):self.lab.history(self.mid,self.student)

if __name__=='__main__':unittest.main()
