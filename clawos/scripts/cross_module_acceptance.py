"""Repeatable service-level regression across product journeys; no external user claims."""
import argparse
import json
from pathlib import Path
import sys
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))

SUITES = {
    'document_questions': 'test_evidence_learning_quality.EvidenceQualityTests',
    'scanned_materials': 'test_document_ocr_service',
    'meeting_transcripts': 'test_workspace_services.WorkspaceServicesTests.test_meeting_audio_sidecar_diarization_and_connector_drafts',
    'office_edits': 'test_office_editing_fidelity',
    'code_repair': 'test_coding_workflow_service',
    'education_materials': 'test_academy_materials',
}


class EvidenceResult(unittest.TestResult):
    def __init__(self):
        super().__init__(); self.rows=[]
    def startTest(self,test):
        super().startTest(test); self.started=time.perf_counter(); self.current=dict(case=test.id(),status='passed',errors=[])
    def addFailure(self,test,err):
        super().addFailure(test,err); self.current.update(status='failed'); self.current['errors'].append(self._exc_info_to_string(err,test))
    def addError(self,test,err):
        super().addError(test,err); self.current.update(status='failed'); self.current['errors'].append(self._exc_info_to_string(err,test))
    def addSkip(self,test,reason):
        super().addSkip(test,reason); self.current.update(status='blocked',errors=[reason])
    def addSubTest(self,test,subtest,err):
        super().addSubTest(test,subtest,err)
        if err:self.current.update(status='failed'); self.current['errors'].append(self._exc_info_to_string(err,test))
    def stopTest(self,test):
        self.current.update(duration_ms=round((time.perf_counter()-self.started)*1000,2),manual_rework_minutes=None,
            human_correctness=None,fixture_origin='developer regression fixture')
        self.rows.append(self.current);super().stopTest(test)


def run():
    rows=[]
    for module,target in SUITES.items():
        result=EvidenceResult();unittest.defaultTestLoader.loadTestsFromName(target).run(result)
        rows.extend(dict(row,module=module) for row in result.rows)
    return dict(schema='cross-module-acceptance.v1',cases=rows,total=len(rows),
        passed=sum(r['status']=='passed' for r in rows),failed=sum(r['status']=='failed' for r in rows),
        blocked=sum(r['status']=='blocked' for r in rows),
        boundary='Service-level developer regression, including injected failures and recovery. OCR/ASR mocks do not measure recognition accuracy. No independent user study, production repair rate, WPS parity, or human rework measurements are claimed.')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='clawos/output/cross-module-acceptance.json');args=parser.parse_args()
    report=run();path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='cases'},ensure_ascii=False));sys.exit(1 if report['failed'] or report['blocked'] else 0)
