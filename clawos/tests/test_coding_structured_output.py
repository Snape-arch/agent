import asyncio
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services import coding_structured_output as structured
from services.autonomous_coding_service import AutonomousCodingService
from services.coding_comparison_service import ComparisonCapture, CodingComparisonService, digest
from services.coding_contracts import CodingContracts
from services.coding_workflow_service import CodingWorkflowService
from services.collaboration_delivery import CollaborationDelivery
import test_reliable_collaboration as fixtures


def contracts():
    return [dict(id='addition', statement='Preserve exact two-argument addition API and return the sum.',
        paths=['a.py'], test_indexes=[0], interface=dict(kind='python_signature',function='add',parameters=['a','b']),
        clauses=[dict(id='api',category='input',statement='Exactly a,b; no optional or variadic parameters.',test_indexes=[0]),
                 dict(id='sum',category='output',statement='Return a+b.',test_indexes=[0])]),
        dict(id='multiplication',statement='Return the product.',paths=['b.py'],test_indexes=[0])]


class SchemaTests(unittest.TestCase):
    def test_compact_decoder_schema_keeps_scope_and_local_bounds(self):
        schema=structured.schema_for('proposal',['a.py'])
        fmt=structured.response_format('proposal',schema)
        decoded=fmt['json_schema']['schema']
        self.assertEqual(fmt['type'],'json_schema')
        self.assertNotIn('maxItems',decoded['properties']['changes'])
        self.assertEqual(decoded['properties']['changes']['items']['anyOf'][0]['properties']['path']['enum'],['a.py'])
        self.assertFalse(decoded['additionalProperties'])
        self.assertEqual(schema['properties']['changes']['maxItems'],20)
        bad=dict(changes=[dict(path='a.py',operation='replace',old_text='x',new_text='y')]*21,test_commands=[['python']])
        with self.assertRaises(ValueError):structured.parse(json.dumps(bad),schema)
    def test_provider_transmits_schema_and_does_not_downgrade_unsupported_format(self):
        from providers.qwen import QwenProvider
        from test_model_provider import FakeHttpClient, FakeResponse
        schema=structured.response_format('reviewer',structured.schema_for('reviewer',['a.py']))
        response=FakeResponse(dict(choices=[dict(message=dict(content='{}'),finish_reason='stop')],usage=dict(total_tokens=2)))
        client=FakeHttpClient(response);provider=QwenProvider({})
        asyncio.run(provider.complete([dict(role='user',content='JSON')],dict(response_format=schema),http_client=client))
        self.assertEqual(client.calls[0]['json']['response_format'],schema)
        failing=FakeHttpClient(error=RuntimeError('schema unsupported'))
        result=asyncio.run(provider.complete([dict(role='user',content='JSON')],dict(response_format=schema),http_client=failing))
        self.assertFalse(result['ok']);self.assertEqual(len(failing.calls),1)
        self.assertEqual(failing.calls[0]['json']['response_format'],schema)
    def test_duplicate_nonfinite_embedded_prose_and_invalid_types_rejected(self):
        schema = structured.schema_for('reviewer',['a.py'])
        for value in ['{"approved":true,"approved":false,"reasons":[],"risks":[]}',
                      '{"approved":1,"reasons":[],"risks":[]}',
                      '{"approved":true,"reasons":[],"risks":[],"confidence":NaN}',
                      'Here is JSON: {"approved":true,"reasons":[],"risks":[]}']:
            with self.subTest(value=value),self.assertRaises(ValueError):structured.parse(value,schema)
        self.assertTrue(structured.parse('```json\n{"approved":true,"reasons":[],"risks":[]}\n```',schema)['approved'])

    def test_edit_union_denies_read_only_path_and_mixed_operation_fields(self):
        schema = structured.schema_for('worker',['a.py'])
        valid=dict(changes=[dict(path='a.py',operation='replace',old_text='old',new_text='new')])
        self.assertEqual(structured.parse(json.dumps(valid),schema),valid)
        for field,value in [('path','dependency.py'),('content','unused')]:
            bad=copy.deepcopy(valid);bad['changes'][0][field]=value
            with self.assertRaises(ValueError):structured.parse(json.dumps(bad),schema)
        for operation in [dict(path='a.py',operation='create',content='new file'),
                          dict(path='a.py',operation='hunks',hunks=[dict(old_text='one',new_text='two')])]:
            structured.parse(json.dumps(dict(changes=[operation])),schema)

    def test_grounded_diagnosis_and_bounds_checked_locally(self):
        schema=structured.schema_for('diagnostician',['a.py'],grounded_targets=[dict(path='a.py',symbol='add')])
        answer=dict(hypothesis='cause',targets=[dict(path='a.py',symbol='wrong')],expected_test_effect='sum passes')
        with self.assertRaises(ValueError):structured.parse(json.dumps(answer),schema)
        schema=structured.schema_for('proposal',['a.py'])
        answer=dict(changes=[dict(path='a.py',operation='create',content='x')],test_commands=[['python']],confidence=1e100)
        with self.assertRaises(ValueError):structured.parse(json.dumps(answer),schema)


class ContractTests(unittest.TestCase):
    def test_clause_binding_validation_and_command_failures_remain_visible(self):
        value=contracts();validated=CodingContracts.validate(value,['a.py','b.py'],[['python']])
        value[0]['clauses'][0]['statement']='mutated'
        self.assertNotEqual(value,validated)
        self.assertEqual(len(CodingContracts.checklist(validated)),3)
        bad=copy.deepcopy(validated);bad[0]['clauses'][0]['test_indexes']=[1]
        with self.assertRaises(ValueError):CodingContracts.validate(bad,['a.py','b.py'],[['python']])
        with self.assertRaises(ValueError):CodingContracts.results(validated,[dict(exit_code=0)],digest)

    def test_signature_checks_defaults_kinds_variadics_duplicates_and_syntax(self):
        with tempfile.TemporaryDirectory() as td:
            repo=Path(td);value=contracts()[:1]
            for source in ['def add(a,b):return a+b', 'def add(a,b,extra=0):return a+b',
                           'def add(a,b=0):return a+b', 'def add(a,*,b):return a+b',
                           'def add(a,b,**kw):return a+b', 'def add(a,b):return a+b\ndef add(a,b):return 0', 'invalid syntax!']:
                (repo/'a.py').write_text(source)
                row=CodingContracts.results(value,[dict(exit_code=0)],digest,repo=repo)[0]
                self.assertEqual(row['passed'],source=='def add(a,b):return a+b')
                self.assertEqual(row['interface']['evidence_kind'],'static_python_signature_only')
            value[0]['interface'].update(keyword_only=['b'],defaults=['b'])
            (repo/'a.py').write_text('def add(a,*,b=0):return a+b')
            self.assertTrue(CodingContracts.results(value,[dict(exit_code=0)],digest,repo=repo)[0]['passed'])
            self.assertFalse(CodingContracts.results(value,[dict(exit_code=1)],digest,repo=repo)[0]['passed'])


class NativeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.repo=fixtures.fixture(self.root)
        import subprocess
        def command(repo,argv,timeout):
            proc=subprocess.run(argv,cwd=repo,capture_output=True,text=True,timeout=timeout)
            return dict(command=argv,exit_code=proc.returncode,stdout=proc.stdout,stderr=proc.stderr,
                sandbox=dict(backend='fixture-native',os_enforced=False))
        self.runner=patch.object(CodingWorkflowService,'_run_command',side_effect=command)
        self.runner.start();self.addCleanup(self.runner.stop)

    async def test_capture_preserves_schema_and_binds_receipt_to_options(self):
        class Provider:
            name='fixture';model='fixture';base_url=''
            async def complete(self,messages,options):
                self.options=copy.deepcopy(options)
                return dict(ok=True,provider=self.name,model=self.model,content='{}',usage=dict(total_tokens=2),raw=dict(choices=[dict(finish_reason='stop')]))
        provider=Provider();caps=CodingComparisonService.limits(None)
        capture=ComparisonCapture(self.root/'capture',caps,{})
        fmt=structured.response_format('reviewer',structured.schema_for('reviewer',['a.py']))
        await capture.wrap(provider).complete([dict(role='user',content='JSON')],dict(response_format=fmt))
        self.assertEqual(provider.options['response_format'],fmt)
        receipt=json.loads((self.root/'capture/answer-1.json').read_text())
        self.assertEqual(receipt['options']['response_format'],fmt)
        self.assertEqual(capture.ledger['reservations'][0]['options'],receipt['options'])

    async def test_single_signature_violation_repaired_before_any_write(self):
        observed=[]
        class Provider:
            async def complete(_,messages,options):
                observed.append(copy.deepcopy((messages,options)))
                new='def add(a,b,extra=0):\n    return a+b' if len(observed)==1 else 'def add(a,b):\n    return a+b'
                return dict(ok=True,content=json.dumps(dict(changes=[dict(path='a.py',operation='replace',old_text='def add(a, b):\n    return a - b',new_text=new)],test_commands=[['python','check.py']])),usage=dict(total_tokens=10),raw=dict(choices=[dict(finish_reason='stop')]))
        before=(self.repo/'a.py').read_bytes()
        result=await AutonomousCodingService(Provider()).propose(self.repo,'Sum with frozen API',focus_paths=['a.py'],
            test_commands=[['python','check.py']],requirements=contracts()[:1])
        self.assertEqual(len(observed),2);self.assertTrue(result['interface_checks'][0]['passed'])
        self.assertEqual((self.repo/'a.py').read_bytes(),before)
        self.assertEqual(observed[0][1]['response_format']['type'],'json_schema')
        self.assertIn('contract checklist',observed[0][0][1]['content'])
        self.assertIn('isinstance accepts subclasses',observed[0][0][0]['content'])

    async def test_multi_cannot_pass_wrong_signature_even_with_passing_commands(self):
        def handler(role,packet):
            result=fixtures.answer(role)
            if role=='a':
                result['changes']=[dict(path='a.py',operation='replace',old_text='def add(a, b):\n    return a - b',
                    new_text='def add(a,b,extra=0):\n    return a+b')]
            return result
        service=fixtures.ReliableCollaborationService(lambda spec:fixtures.Provider(spec.role_id,handler),root=self.root/'runs')
        result=await service.run(self.repo,'Fix arithmetic, preserve exact API',allowed_paths=['a.py','b.py'],
            test_commands=[[sys.executable,'-B','check.py']],requirements=contracts(),confirmed=True)
        self.assertEqual(result['status'],'contract_failed',result)
        self.assertTrue(all(t['exit_code']==0 for t in result['integration']['tests']))
        self.assertFalse(result['requirement_results'][0]['passed'])
        with self.assertRaises(ValueError):await CollaborationDelivery(service).prepare(result['run_id'],confirmed=True)

    async def test_clause_and_interface_receipts_survive_native_delivery_replay(self):
        observed=[]
        class Provider(fixtures.Provider):
            async def complete(self,messages,options):
                observed.append(copy.deepcopy(messages))
                return await super().complete(messages,options)
        service=fixtures.ReliableCollaborationService(lambda spec:Provider(spec.role_id),root=self.root/'runs')
        value=contracts()
        result=await service.run(self.repo,'Fix arithmetic and preserve the caller interface',allowed_paths=['a.py','b.py'],
            test_commands=[[sys.executable,'-B','check.py']],requirements=value,confirmed=True)
        self.assertEqual(result['status'],'passed',result)
        delivery=CollaborationDelivery(service)
        packet=await delivery.prepare(result['run_id'],confirmed=True)
        self.assertEqual(packet['manifest']['requirements'],value)
        row=packet['manifest']['requirement_results'][0]
        self.assertTrue(row['interface']['passed']);self.assertEqual(len(row['clauses']),2)
        self.assertEqual(delivery.inspect(result['run_id'])['status'],'ready')
        self.assertTrue(observed)
        self.assertTrue(all('isinstance accepts subclasses' in m[0]['content'] for m in observed))


if __name__=='__main__':unittest.main()
