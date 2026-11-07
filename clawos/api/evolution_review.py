"""Evolution review HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request
import asyncio
import json


class EvolutionReviewAPI:
    def __init__(self, *,
        _collaboration: Callable[..., Any],
        _evolution_json: Callable[..., Any],
        memory_store_provider: Callable[[], Any],
    ):
        self._collaboration = _collaboration
        self._evolution_json = _evolution_json
        self.memory_store_provider = memory_store_provider
        self.router = APIRouter()
        self.router.add_api_route('/api/evolution-review/{experiment_id}/packet', self.api_evolution_assigned_packet, methods=['GET'])
        self.router.add_api_route('/api/evolution-review/{experiment_id}/ratings', self.api_evolution_assigned_ratings, methods=['POST'])
        self.router.add_api_route('/api/evolution-review/{experiment_id}/adjudication', self.api_evolution_assigned_adjudication, methods=['POST'])

    def _evolution_review_access(self, experiment_id,request,role=None):
        if not self.memory_store_provider(): raise HTTPException(503,'MemoryOS not initialized')
        from services.evolution_review import EvolutionReviewService
        identity=self._collaboration().identity(request)
        service=EvolutionReviewService(self.memory_store_provider())
        try: assigned=service.require_grant(experiment_id,identity['id'],role)
        except PermissionError as exc: raise HTTPException(403,str(exc))
        return service,identity,assigned


    async def api_evolution_assigned_packet(self, experiment_id:int,request:Request):
        service,identity,role=self._evolution_review_access(experiment_id,request)
        packet=service.packet(experiment_id)
        summary=service.summary(experiment_id)
        packet['instructions']='Score both options independently with reasons. Identity is bound to the assigned server session. Submitted judgments are immutable.'
        if role=='adjudicator':
            issues=set(summary['authenticated_adjudication_required'])|{row['entry_id'] for row in summary['authenticated_critical_errors']}
            packet['entries']=[entry for entry in packet['entries'] if entry['entry_id'] in issues]
            evidence=service.evidence(experiment_id)
            packet['prior_ratings']=[{'reviewer':index+1,'ratings':[rating for rating in review['ratings'] if rating['entry_id'] in issues]} for index,review in enumerate(evidence['reviews'])
                                     if review.get('authentication')]
        # Reviewers must not see other scores or control/candidate aggregates before
        # submitting their own judgment. Adjudicators see only assigned conflicts.
        with self.memory_store_provider()._conn() as conn:
            own=conn.execute('SELECT submission FROM evolution_reviews WHERE experiment_id=? AND reviewer=?',
                             (experiment_id,'session:'+identity['id'])).fetchone()
            submitted=bool(own)
            if role=='reviewer' and own:
                packet['own_ratings']=json.loads(own['submission'])['ratings']
        safe_summary={key:summary[key] for key in ('authenticated_reviewer_count','authenticated_review_set_digest',
                      'authenticated_resolved_entries','provider_execution_verified','real_person_independence_verified')}
        safe_summary['submitted']=submitted
        return {'packet':packet,'viewer':identity,'role':role,'summary':safe_summary}


    async def api_evolution_assigned_ratings(self, experiment_id:int,request:Request):
        service,identity,_=self._evolution_review_access(experiment_id,request,'reviewer')
        data=await self._evolution_json(request)
        try: return {'summary':await asyncio.to_thread(service.submit,experiment_id,data,authenticated_uid=identity['id'],
            authorization_check=lambda:self._collaboration().identity(request)['id']==identity['id'])}
        except PermissionError as exc: raise HTTPException(403,str(exc))
        except (ValueError,TypeError,AttributeError) as exc: raise HTTPException(400,str(exc))


    async def api_evolution_assigned_adjudication(self, experiment_id:int,request:Request):
        service,identity,_=self._evolution_review_access(experiment_id,request,'adjudicator')
        data=await self._evolution_json(request)
        try: return {'summary':await asyncio.to_thread(service.adjudicate,experiment_id,data,identity['id'],
            authorization_check=lambda:self._collaboration().identity(request)['id']==identity['id'])}
        except PermissionError as exc: raise HTTPException(403,str(exc))
        except (ValueError,TypeError,AttributeError) as exc: raise HTTPException(400,str(exc))
