"""Evidence engine router + isolated response hooks installed by main's include.

Keeps plan.py and existing config implementation untouched. Logging failure never
breaks a plan; config coverage is extended without exposing any private config.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from . import evidence_queue

LOG = logging.getLogger(__name__)
router = APIRouter()


@router.get('/api/evidence/queue')
def evidence_queue_get(limit: int = Query(100, ge=1, le=1000), bbox: str | None = None,
                       min_score: float = Query(0, ge=0)):
    bounds = None
    if bbox:
        import math
        try:
            bounds = tuple(float(x) for x in bbox.split(','))
            if len(bounds) != 4 or not all(math.isfinite(v) for v in bounds) or bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
                raise ValueError()
        except ValueError:
            raise HTTPException(422, 'bbox must be west,south,east,north')
    return evidence_queue.queue(limit, bounds, min_score)


class EvidenceHooks:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or (scope.get('method'), scope.get('path')) not in (
                ('GET', '/api/config'), ('POST', '/api/plan')):
            return await self.app(scope, receive, send)
        start, chunks = None, []
        size = 0
        passthrough = False

        async def capture(message):
            nonlocal start, size, passthrough
            if message['type'] == 'http.response.start':
                if message['status'] != 200:
                    passthrough = True
                    return await send(message)
                start = message
                return
            if passthrough:
                return await send(message)
            if message['type'] != 'http.response.body':
                return await send(message)
            chunks.append(message.get('body', b''))
            size += len(chunks[-1])
            if message.get('more_body', False):
                if size > 16 * 1024 * 1024:
                    passthrough = True
                    await send(start)
                    await send({'type':'http.response.body','body':b''.join(chunks),'more_body':True})
                    chunks.clear()
                return
            body = b''.join(chunks)
            try:
                result = json.loads(body)
                if scope['path'] == '/api/config':
                    state = await run_in_threadpool(evidence_queue.city_state)
                    result.setdefault('coverage', {}).update(state.get('coverage', {}))
                    body = json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode()
                    start = {**start, 'headers':[(k,v) for k,v in start['headers'] if k.lower() not in (b'content-length', b'etag')]}
                    start['headers'].append((b'content-length', str(len(body)).encode()))
                else:
                    ids = await run_in_threadpool(evidence_queue.touched_way_ids, result)
                    await run_in_threadpool(evidence_queue.record_way_ids, ids)
            except Exception as exc:
                LOG.warning('Evidence response hook failed (%s)', type(exc).__name__)
            await send(start)
            await send({'type':'http.response.body','body':body,'more_body':False})

        await self.app(scope, receive, capture)


def router_for(app):
    app.add_middleware(EvidenceHooks)
    return router
