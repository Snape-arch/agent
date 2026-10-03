"""Actual HTTP acceptance using synthetic labels in an owned isolated preview."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.evolution_experiments import digest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:18918')
    parser.add_argument('--out', default=str(ROOT / 'output' / 'evolution-experiments-http-20261003'))
    args = parser.parse_args()
    out = Path(args.out).resolve()
    if not out.is_relative_to((ROOT / 'output').resolve()):
        parser.error('output must stay inside ignored clawos/output')
    checks = []
    with httpx.Client(base_url=args.url, timeout=190) as client:
        marker = client.get('/api/qa/environment').json()
        assert marker.get('isolated') and not marker.get('models_enabled'), marker
        checks.append('owned isolated preview, models disabled')
        cases = [{'id': f'fixture-{i}', 'group_id': f'fixture-group-{i}', 'query': f'Fixture read-only routing case {i}',
                  'reviewed_by': 'synthetic-acceptance-fixture', 'origin': 'curated',
                  'route': {'allowed_tools': ['file_read','file_write','shell_exec','web_fetch','web_search']},
                  'required_tools': ['file_read'], 'forbidden_tools': ['file_write','shell_exec','web_fetch']}
                 for i in range(200)]
        payload = dict(target_type='tool_routing_policy', target_key='http-acceptance', baseline_payload={}, cases=cases)
        pool = client.post('/api/self-evolution/candidates', json=dict(target_type='retrieval_params', baseline_payload={'top_k':10}, mine_reflections=True))
        pool.raise_for_status()
        assert len(pool.json()['candidates']) >= 2 and not pool.json()['verified_gain']
        checks.append('bounded candidate pool does not claim gains')
        cross_site = client.post('/api/self-evolution/experiments', json=payload, headers={'origin':'https://untrusted.example'})
        assert cross_site.status_code == 403
        checks.append('cross-site write rejected')
        bad = json.loads(json.dumps(payload))
        bad['cases'][1]['query'] = bad['cases'][0]['query']
        assert client.post('/api/self-evolution/experiments', json=bad).status_code == 400
        checks.append('duplicate input rejected')
        response = client.post('/api/self-evolution/experiments', json=payload)
        response.raise_for_status()
        experiment = response.json()['experiment']
        eid = experiment['id']
        assert client.post('/api/self-evolution/experiments', json=payload).json()['experiment']['id'] == eid
        checks.append('freezing idempotent')
        # A prior completed acceptance run is downloaded, never overwritten.
        if experiment['status'] == 'frozen':
            response = client.post(f'/api/self-evolution/experiments/{eid}/replay')
            response.raise_for_status()
            experiment = response.json()['experiment']
        else:
            experiment = client.get(f'/api/self-evolution/experiments/{eid}').json()['experiment']
        report = experiment['report']
        assert report['eligible_for_regression_queue'] and report['holdout_groups'] >= 30, report['gates']
        assert not report['holdout_used_for_selection'] and not report['runtime_promotion_evidence']
        checks.append('actual paired routing contract replay and independent holdout')
        unsigned = {key:value for key,value in report.items() if key != 'report_digest'}
        assert digest(unsigned) == report['report_digest']
        assert digest(experiment['definition']) == experiment['definition_digest']
        checks.append('report and frozen-input fingerprints match')
        assert client.post(f'/api/self-evolution/experiments/{eid}/replay').status_code == 409
        checks.append('completed evidence cannot be overwritten')
        response = client.post(f'/api/self-evolution/experiments/{eid}/nominate', json={})
        response.raise_for_status()
        run = response.json()['run']
        assert run['status'] == 'candidate'
        assert client.post(f'/api/self-evolution/experiments/{eid}/nominate', json={}).json()['run']['id'] == run['id']
        checks.append('idempotent candidate nomination')
        board = client.get('/api/self-evolution/board').json()
        item = next(item for item in board['runs'] if item['id'] == run['id'])
        assert item['paired_quality_evidence']['matched_task_count'] == 0 and not item['paired_quality_evidence']['passed']
        assert not board['enterprise_ready'] and not item['owns_active_policy']
        assert client.post(f'/api/self-evolution/runs/{run["id"]}/canary',json={}).status_code == 400
        checks.append('offline replay never bypasses live release stages')
    out.mkdir(parents=True, exist_ok=True)
    result = dict(checks=checks, passed=len(checks), fixture_scope='synthetic HTTP contract acceptance; no production quality gain claim',
                  marker=marker, experiment_id=eid, report_digest=report['report_digest'], definition_digest=experiment['definition_digest'],
                  source_sha256=experiment['definition']['source_sha256'], holdout_groups=report['holdout_groups'])
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    main()
