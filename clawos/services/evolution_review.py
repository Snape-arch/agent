"""Immutable outputs, session-bound review and snapshot-bound adjudication.

Session possession does not verify a real person or reviewer independence.
Review evidence never becomes live release signals automatically.
"""
from __future__ import annotations

import json
import math
import secrets
import uuid
from collections import defaultdict

from services.evolution_experiments import digest
from services.learning_governance import stratified_quality_report


class EvolutionReviewService:
    def __init__(self, store):
        self.store = store

    def freeze_outputs(self, experiment_id, payload, created_by='console', *, captured=False):
        if not isinstance(payload, dict):
            raise ValueError('output package must be an object')
        with self.store.transaction() as conn:
            experiment = self.store.get_evolution_experiment(experiment_id)
            if not experiment or experiment['status'] != 'completed':
                raise ValueError('review requires a completed, search-selected experiment')
            definition, report = experiment['definition'], experiment['report']
            if (payload.get('definition_digest') != experiment['definition_digest']
                    or payload.get('report_digest') != report.get('report_digest')
                    or report.get('selected_candidate_id') == 'baseline'):
                raise ValueError('outputs must bind the completed definition and selected candidate report')
            records = payload.get('outputs')
            expected = {case['id']: case for case in definition['cases'] if case['split'] == 'holdout'}
            if not isinstance(records, list) or len(records) != len(expected):
                raise ValueError('one paired model output per frozen holdout case is required')
            seen, normalized = set(), []
            for record in records:
                cid = record.get('case_id')
                if cid not in expected or cid in seen or record.get('input_digest') != expected[cid]['input_digest']:
                    raise ValueError('unknown, duplicate or mismatched frozen input')
                seen.add(cid)
                variants = record.get('variants')
                if not isinstance(variants, dict) or set(variants) != {'control', 'candidate'}:
                    raise ValueError('paired control/candidate outputs are required')
                cleaned = {}
                for variant, policy in [('control', definition['baseline_payload']), ('candidate', report['selected_payload'])]:
                    value = variants[variant]
                    text = value.get('text')
                    if (not isinstance(text, str) or not text.strip() or len(text) > 24000
                            or value.get('policy_digest') != digest(policy)
                            or not isinstance(value.get('provider'), str) or not value['provider'].strip()
                            or not isinstance(value.get('model'), str) or not value['model'].strip()):
                        raise ValueError('each bounded model output needs provider/model and the exact policy digest')
                    cleaned[variant] = {'text': text, 'text_digest': digest(text), 'policy_digest': digest(policy),
                                        'provider': value['provider'][:120], 'model': value['model'][:120]}
                normalized.append({'case_id': cid, 'input_digest': expected[cid]['input_digest'], 'variants': cleaned})
            normalized.sort(key=lambda row: row['case_id'])
            receipt_digests=[]
            if captured:
                from services.evolution_capture import EvolutionModelCapture
                receipts={(row['case_id'],row['variant']):row for row in EvolutionModelCapture(self.store).receipts(experiment_id)}
                for record in normalized:
                    for variant,value in record['variants'].items():
                        receipt=receipts.get((record['case_id'],variant))
                        if (not receipt or receipt['request']['input_digest']!=record['input_digest']
                                or receipt['request']['policy_digest']!=value['policy_digest']
                                or any(receipt[key]!=value[key] for key in ('text','text_digest','provider','model'))):
                            raise ValueError('model output does not match an application-captured receipt')
                        receipt_digests.append(receipt['receipt_digest'])
            import_digest = digest(normalized)
            previous = conn.execute('SELECT payload FROM evolution_review_packets WHERE experiment_id=?', (experiment_id,)).fetchone()
            if previous:
                if json.loads(previous['payload'])['import_digest'] != import_digest:
                    raise ValueError('reviewed outputs are immutable; cannot replace a packet')
                return self.packet(experiment_id)
            entries = []
            for record in normalized:
                case = expected[record['case_id']]
                order = ['control', 'candidate']
                if secrets.randbelow(2):
                    order.reverse()
                entries.append({'entry_id': uuid.uuid4().hex, 'case_id': case['id'], 'query': case['query'],
                                'group_id': case['group_id'], 'segment': case.get('segment', 'default'),
                                'input_digest': case['input_digest'],
                                'options': {label: record['variants'][variant] for label, variant in zip(('A','B'), order)},
                                'mapping': dict(zip(('A','B'), order))})
            frozen = {'schema': 'clawos.blinded-review.v1', 'experiment_id': experiment_id,
                      'definition_digest': experiment['definition_digest'], 'report_digest': report['report_digest'],
                      'import_digest': import_digest, 'entries': entries,
                      'created_by': str(created_by)[:120], 'capture_receipt_digests':receipt_digests,
                      'provider_execution_verified': bool(captured),
                      'provenance': 'application-captured provider responses' if captured else 'externally supplied model outputs; execution unverified'}
            if len(json.dumps(frozen, ensure_ascii=False).encode()) > 8 * 1024 * 1024:
                raise ValueError('review output packet exceeds 8MiB')
            conn.execute('INSERT INTO evolution_review_packets(experiment_id,packet_digest,payload,created_by) VALUES (?,?,?,?)',
                         (experiment_id, digest(frozen), json.dumps(frozen, ensure_ascii=False), frozen['created_by']))
            return self.packet(experiment_id)

    def _load(self, experiment_id):
        with self.store._conn() as conn:
            row = conn.execute('SELECT * FROM evolution_review_packets WHERE experiment_id=?', (experiment_id,)).fetchone()
        if not row:
            raise ValueError('no frozen review output packet')
        frozen = json.loads(row['payload'])
        if digest(frozen) != row['packet_digest']:
            raise ValueError('review packet digest mismatch')
        return frozen, row['packet_digest']

    def packet(self, experiment_id):
        frozen, packet_digest = self._load(experiment_id)
        # Provider names, policy hashes and variant identities would unblind it.
        return {'schema': frozen['schema'], 'experiment_id': experiment_id, 'packet_digest': packet_digest,
                'instructions': 'Score A and B independently (0..1) with rationale. Do not infer variant identity. Two named reviewers required; identities are self-reported.',
                'entries': [{'entry_id': row['entry_id'], 'query': row['query'],
                             'options': {label: {'text': value['text'], 'text_digest': value['text_digest']}
                                         for label, value in row['options'].items()}} for row in frozen['entries']],
                'blindness': 'procedural export only; owners with source access can unblind',
                'runtime_promotion_evidence': False}

    def submit(self, experiment_id, payload, *, authenticated_uid=None, authorization_check=None):
        if not isinstance(payload, dict):
            raise ValueError('review must be an object')
        with self.store.transaction() as conn:
            if authorization_check and authorization_check() is not True:
                raise PermissionError('review session changed or expired')
            frozen, packet_digest = self._load(experiment_id)
            reviewer = str(payload.get('reviewer') or '').strip()
            if authenticated_uid:
                self.require_grant(experiment_id,authenticated_uid,'reviewer')
                reviewer='session:'+authenticated_uid
            elif reviewer.startswith('session:'):
                raise ValueError('session reviewer identities must come from authenticated requests')
            if not reviewer or len(reviewer) > 120 or reviewer == frozen['created_by']:
                raise ValueError('a named reviewer different from the output submitter is required')
            if payload.get('packet_digest') != packet_digest:
                raise ValueError('review does not bind this immutable packet')
            ratings = payload.get('ratings')
            expected = {row['entry_id']: row for row in frozen['entries']}
            if not isinstance(ratings, list) or len(ratings) != len(expected):
                raise ValueError('review every entry and both options')
            seen, cleaned = set(), []
            for row in ratings:
                eid = row.get('entry_id')
                if eid not in expected or eid in seen or set(row.get('options') or {}) != {'A','B'}:
                    raise ValueError('unknown/duplicate entry or missing option')
                seen.add(eid)
                options = {}
                for label, value in row['options'].items():
                    score = value.get('score')
                    rationale = value.get('rationale')
                    if (isinstance(score, bool) or not isinstance(score, (int,float)) or not math.isfinite(score) or not 0 <= score <= 1
                            or not isinstance(rationale, str) or not rationale.strip() or len(rationale) > 2000
                            or type(value.get('critical_error', False)) is not bool
                            or value.get('text_digest') != expected[eid]['options'][label]['text_digest']):
                        raise ValueError('finite 0..1 score, rationale and exact text digest are required')
                    options[label] = {'score': score, 'rationale': rationale, 'text_digest': value['text_digest'],
                                      'critical_error': value.get('critical_error', False)}
                cleaned.append({'entry_id': eid, 'options': options})
            submission = {'packet_digest': packet_digest, 'reviewer': reviewer, 'ratings': sorted(cleaned, key=lambda row: row['entry_id'])}
            if authenticated_uid:
                submission['authentication']={'kind':'server_collaboration_session','user_id':authenticated_uid}
            previous = conn.execute('SELECT submission_digest FROM evolution_reviews WHERE experiment_id=? AND reviewer=?', (experiment_id, reviewer)).fetchone()
            if previous and previous['submission_digest'] != digest(submission):
                raise ValueError('review observations are immutable; cannot overwrite a judgment')
            if not previous:
                count = conn.execute('SELECT count(*) FROM evolution_reviews WHERE experiment_id=?', (experiment_id,)).fetchone()[0]
                if count >= 5:
                    raise ValueError('at most five reviewers per packet')
                conn.execute('INSERT INTO evolution_reviews(experiment_id,reviewer,submission,submission_digest) VALUES (?,?,?,?)',
                             (experiment_id, reviewer, json.dumps(submission, ensure_ascii=False), digest(submission)))
            return self.summary(experiment_id)

    def summary(self, experiment_id):
        frozen, packet_digest = self._load(experiment_id)
        with self.store._conn() as conn:
            raw = conn.execute('SELECT * FROM evolution_reviews WHERE experiment_id=? ORDER BY reviewer', (experiment_id,)).fetchall()
        reviews = [json.loads(row['submission']) for row in raw]
        if any(digest(value) != row['submission_digest'] for value, row in zip(reviews, raw)):
            raise ValueError('review observation digest mismatch')
        result=self._assess(frozen,packet_digest,reviews)
        authenticated=[review for review in reviews if (review.get('authentication') or {}).get('kind')=='server_collaboration_session'
                       and review['reviewer']=='session:'+review['authentication']['user_id']]
        verified=self._assess(frozen,packet_digest,authenticated)
        result.update(authenticated_reviewer_count=len(authenticated),authenticated_review_passed=verified['reported_review_passed'],
                      authenticated_reviewed_gate=verified['reviewed_gate'],
                      authenticated_review_set_digest=verified['review_set_digest'],
                      authenticated_adjudication_required=verified['adjudication_required'],
                      authenticated_critical_errors=verified['critical_errors'],
                      authenticated_resolved_entries=verified['resolved_entries'],
                      reviewer_session_authenticated=len(authenticated)>=2,
                      reviewer_identity_verified=False, real_person_independence_verified=False,
                      provider_execution_verified=frozen.get('provider_execution_verified',False))
        return result

    def _assess(self, frozen, packet_digest, reviews):
        review_set_digest=digest(sorted(reviews,key=lambda review:review['reviewer']))
        with self.store._conn() as conn:
            records=conn.execute('SELECT * FROM evolution_adjudications WHERE experiment_id=? AND review_set_digest=?',
                                 (frozen['experiment_id'],review_set_digest)).fetchall()
        decisions={}
        for row in records:
            decision=json.loads(row['decision'])
            if digest(decision)!=row['decision_digest']: raise ValueError('adjudication digest mismatch')
            decisions[row['entry_id']]=decision
        outcomes = defaultdict(lambda: defaultdict(list))
        critical, disagreements = [], []
        for review in reviews:
            for rating in review['ratings']:
                for label, value in rating['options'].items():
                    outcomes[rating['entry_id']][label].append(value['score'])
                    if value['critical_error'] and rating['entry_id'] not in decisions:
                        critical.append({'entry_id': rating['entry_id'], 'option': label, 'reviewer': review['reviewer']})
        signals = []
        for row in frozen['entries']:
            values = outcomes[row['entry_id']]
            if not values:
                continue
            decision=decisions.get(row['entry_id'])
            if not decision and any(max(scores) - min(scores) > .25 for scores in values.values()):
                disagreements.append(row['entry_id'])
            for label, variant in row['mapping'].items():
                scores = [decision['options'][label]['score']] if decision else values[label]
                if decision and decision['options'][label]['critical_error']:
                    critical.append({'entry_id':row['entry_id'],'option':label,'reviewer':'adjudicator'})
                signals.append({'signal_type': 'quality_score', 'value': sum(scores)/len(scores),
                                'metadata': {'evidence_id': row['case_id'], 'input_digest': row['input_digest'],
                                             'cluster_id': row['group_id'], 'segment': row['segment'], 'variant': variant}})
        gate = stratified_quality_report(signals)
        return {'schema': 'clawos.review-summary.v1', 'packet_digest': packet_digest, 'reviewer_count': len(reviews),
                'case_count': len(frozen['entries']), 'critical_errors': critical, 'adjudication_required': disagreements,
                'reviewed_gate': gate, 'reported_review_passed': len(reviews) >= 2 and not critical and not disagreements and gate['passed'],
                'review_set_digest':review_set_digest,'resolved_entries':len(decisions),
                'reviewer_identity_verified': False, 'provider_execution_verified': False,
                'semantic_entailment_verified': False, 'runtime_promotion_evidence': False,
                'meaning': 'reported blinded ratings only; never grants automatic policy publication'}

    def grant(self, experiment_id, uid, role, actor='local-user'):
        if role not in ('reviewer','adjudicator','revoked') or uid=='local-user':
            raise ValueError('assign another session user a reviewer or adjudicator role')
        with self.store.transaction() as conn:
            frozen,_=self._load(experiment_id)
            if uid==frozen['created_by']: raise ValueError('output submitter cannot review or adjudicate')
            if not conn.execute('SELECT 1 FROM collaboration_users WHERE id=?',(uid,)).fetchone():
                raise ValueError('existing server-issued collaboration user required')
            previous=conn.execute('SELECT role FROM evolution_review_grants WHERE experiment_id=? AND user_id=?',(experiment_id,uid)).fetchone()
            if role=='revoked':
                if not previous: raise ValueError('review grant not found')
                conn.execute('UPDATE evolution_review_grants SET active=0 WHERE experiment_id=? AND user_id=?',(experiment_id,uid))
            else:
                if previous and previous['role']!=role: raise ValueError('reviewer/adjudicator roles cannot be swapped')
                conn.execute('INSERT INTO evolution_review_grants VALUES (?,?,?,1,?) ON CONFLICT(experiment_id,user_id) DO UPDATE SET active=1',
                             (experiment_id,uid,role,actor))
        return {'experiment_id':experiment_id,'user_id':uid,'role':role}

    def require_grant(self, experiment_id, uid, role=None):
        with self.store._conn() as conn:
            row=conn.execute('SELECT role FROM evolution_review_grants WHERE experiment_id=? AND user_id=? AND active=1',(experiment_id,uid)).fetchone()
        if not row or (role and row['role']!=role): raise PermissionError('no active review role for this experiment')
        return row['role']

    def adjudicate(self, experiment_id, payload, uid, *, authorization_check=None):
        with self.store.transaction() as conn:
            if authorization_check and authorization_check() is not True:
                raise PermissionError('adjudicator session changed or expired')
            self.require_grant(experiment_id,uid,'adjudicator')
            frozen,packet_digest=self._load(experiment_id)
            if not isinstance(payload,dict): raise ValueError('adjudication must be an object')
            raw=conn.execute('SELECT submission,submission_digest FROM evolution_reviews WHERE experiment_id=?',(experiment_id,)).fetchall()
            reviews=[json.loads(row['submission']) for row in raw]
            if any(digest(review)!=row['submission_digest'] for review,row in zip(reviews,raw)):
                raise ValueError('review observation digest mismatch')
            if any((review.get('authentication') or {}).get('user_id')==uid for review in reviews):
                raise ValueError('original reviewer cannot adjudicate')
            authenticated=[review for review in reviews if (review.get('authentication') or {}).get('kind')=='server_collaboration_session'
                           and review['reviewer']=='session:'+review['authentication']['user_id']]
            snapshot=digest(sorted(authenticated,key=lambda review:review['reviewer']))
            if len(authenticated)<2 or payload.get('review_set_digest')!=snapshot or payload.get('packet_digest')!=packet_digest:
                raise ValueError('adjudication must bind two authenticated reviews and their current snapshot')
            required=self._assess(frozen,packet_digest,authenticated)
            disputed=set(required['adjudication_required'])|{row['entry_id'] for row in required['critical_errors']}
            entry=next((row for row in frozen['entries'] if row['entry_id']==payload.get('entry_id')),None)
            if not entry: raise ValueError('unknown adjudication entry')
            options=payload.get('options')
            if not isinstance(options,dict) or set(options)!={'A','B'}: raise ValueError('adjudicate both options')
            cleaned={}
            for label,value in options.items():
                score=value.get('score'); rationale=value.get('rationale')
                if (isinstance(score,bool) or not isinstance(score,(int,float)) or not math.isfinite(score) or not 0<=score<=1
                        or not isinstance(rationale,str) or not rationale.strip() or len(rationale)>2000
                        or type(value.get('critical_error')) is not bool or value.get('text_digest')!=entry['options'][label]['text_digest']):
                    raise ValueError('bounded score, rationale, error decision and exact text digest required')
                cleaned[label]={key:value[key] for key in ('score','rationale','critical_error','text_digest')}
            decision={'packet_digest':packet_digest,'review_set_digest':snapshot,'entry_id':entry['entry_id'],
                      'adjudicator':uid,'options':cleaned}
            previous=conn.execute('SELECT decision_digest FROM evolution_adjudications WHERE experiment_id=? AND entry_id=? AND review_set_digest=?',
                                  (experiment_id,entry['entry_id'],snapshot)).fetchone()
            if previous:
                if previous['decision_digest']!=digest(decision): raise ValueError('adjudication is immutable')
                return self.summary(experiment_id)
            if entry['entry_id'] not in disputed: raise ValueError('entry has no unresolved review issue')
            conn.execute('INSERT INTO evolution_adjudications VALUES (?,?,?,?,?,?)',
                         (experiment_id,entry['entry_id'],snapshot,uid,json.dumps(decision,ensure_ascii=False),digest(decision)))
            return self.summary(experiment_id)

    def evidence(self, experiment_id):
        frozen, packet_digest = self._load(experiment_id)
        with self.store._conn() as conn:
            reviews = [json.loads(row[0]) for row in conn.execute('SELECT submission FROM evolution_reviews WHERE experiment_id=? ORDER BY reviewer', (experiment_id,))]
            adjudications=[json.loads(row[0]) for row in conn.execute('SELECT decision FROM evolution_adjudications WHERE experiment_id=? ORDER BY entry_id,review_set_digest',(experiment_id,))]
        return {'packet_digest': packet_digest, 'frozen_outputs_and_mapping': frozen,
                'reviews': reviews, 'adjudications':adjudications,'summary': self.summary(experiment_id)}
