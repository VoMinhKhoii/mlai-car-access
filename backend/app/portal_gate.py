"""Shared portal slots with isolated API/crawler backoff and conservative learning.

Legacy API processes keep using cooldown.json and interval_s=.5 in the lease;
crawler-only state cannot impose hours of local API backoff or a long rate wait.
No proxy, identity change, alternative endpoint or response body is involved.
"""
from __future__ import annotations
from . import fcntl_compat as fcntl
import json
import os
import threading
import time
from contextlib import contextmanager
from .config import CACHE

DIRECTORY = CACHE / 'parcels_points'
_threads = threading.BoundedSemaphore(2)
_role = 'api'


def _read(name):
    try:return json.loads((DIRECTORY / name).read_text())
    except (OSError, ValueError):return {}


def _write(name, value):
    path = DIRECTORY / name
    tmp = path.with_suffix(f'.{os.getpid()}.{threading.get_ident()}.tmp')
    tmp.write_text(json.dumps(value))
    os.replace(tmp, path)


def event(kind, **fields):
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    row = {'at': time.time(), 'kind': kind, 'role': _role, 'pid': os.getpid(), **fields}
    with (DIRECTORY / 'portal_events.jsonl').open('a') as output:
        fcntl.flock(output, fcntl.LOCK_EX)
        output.write(json.dumps(row, separators=(',', ':')) + '\n')


def learned_spacing(minimum=180.0):
    """Use configured failed spacings, not hour-long ban recovery gaps as a quota."""
    failed, successes, pending = [], 0, {}
    try:
        with (DIRECTORY / 'portal_events.jsonl').open() as source:
            for line in source:
                try:row=json.loads(line)
                except ValueError:continue
                if row.get('role') != 'crawler':continue
                pid=row.get('pid')
                if row.get('kind') == 'request_start':pending[pid]=float(row.get('interval_s', 0))
                if row.get('kind') == 'response':
                    if row.get('locked') and pid in pending:failed.append(pending[pid])
                    elif not row.get('locked'):successes += 1
    except OSError:pass
    stored=_read('crawler_backoff.json')
    largest=max(failed, default=0)
    interval=max(minimum, 2*largest, float(stored.get('interval_s', 0)))
    return {'interval_s':interval,'minimum_s':minimum,'largest_failed_configured_spacing_s':largest,
            'historical_success_responses':successes,'historical_locked_responses':len(failed),
            'safe_spacing_established':False,
            'rule':'never decrease; at least minimum, twice failed configured spacing, and persisted learned spacing'}


def crawler_active(lease=None):
    lease = _read('crawler_lease.json') if lease is None else lease
    if lease.get('until', 0) <= time.time():return False
    try:
        os.kill(int(lease['pid']), 0)
        return True
    except (OSError, KeyError, ValueError):return False


def configure_crawler(deadline, interval=180.0):
    global _role
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    with (DIRECTORY / 'lease.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = _read('crawler_lease.json')
        if crawler_active(previous) and previous.get('pid') != os.getpid():
            raise RuntimeError('Another live crawler owns the portal lease')
        with (DIRECTORY / 'backoff.lock').open('a+') as backoff_lock:
            fcntl.flock(backoff_lock, fcntl.LOCK_EX)
            legacy=_read('cooldown.json')
            if legacy.get('owner') == 'crawler':
                current=_read('crawler_backoff.json')
                if legacy.get('until', 0)>current.get('until', 0):_write('crawler_backoff.json', legacy)
                _write('cooldown.json', {'until':0,'interval_s':.5,'migrated_at':time.time()})
        learning=learned_spacing(interval)
        _write('crawler_lease.json', {'pid':os.getpid(),'until':deadline,'interval_s':.5,
                                      'crawler_interval_s':learning['interval_s'],'policy_version':4})
        _role='crawler'
        event('spacing_learned', **learning)
        return learning


def release_crawler():
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    with (DIRECTORY / 'lease.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if _read('crawler_lease.json').get('pid') == os.getpid():_write('crawler_lease.json', {})


def cooldown_until():
    api=_read('cooldown.json')
    api_until=float(api.get('until', 0)) if api.get('owner') == 'api' else 0.0
    if _role == 'api':return api_until
    if not crawler_active():return 0.0
    return max(api_until,float(_read('crawler_backoff.json').get('until', 0)))


def observe_api_backoff():
    """A real API lock also pauses the crawler for the stricter recovery policy."""
    if _role != 'crawler' or not crawler_active():return
    api=_read('cooldown.json');own=_read('crawler_backoff.json')
    incident=api.get('incident_at',0)
    if api.get('owner') != 'api' or api.get('until',0)<=time.time() or incident<=own.get('observed_api_incident_at',0):return
    until=backoff()
    with (DIRECTORY/'backoff.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        data=_read('crawler_backoff.json');data['observed_api_incident_at']=incident
        _write('crawler_backoff.json',data)
    event('api_lock_adopted',until=until,api_incident_at=incident)


def request_interval():
    if _role == 'api':
        own=_read('cooldown.json')
        return max(.5,min(30,float(own.get('interval_s',.5)))) if own.get('owner') == 'api' and own.get('until',0)>time.time() else .5
    lease=_read('crawler_lease.json')
    if not crawler_active(lease):return .5
    return max(float(lease.get('crawler_interval_s', lease.get('interval_s',180))),
               float(_read('crawler_backoff.json').get('interval_s',0)))


def backoff(seconds=None):
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    crawler=_role == 'crawler'
    name='crawler_backoff.json' if crawler else 'cooldown.json'
    base=(7200 if crawler else 600) if seconds is None else seconds
    cap=28800 if crawler else max(base,600)
    with (DIRECTORY / 'backoff.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous=_read(name)
        incident=previous.get('incident_at',0)
        fresh=time.time()-incident>60
        same_policy=previous.get('policy_version') == 4
        recovery=base
        if crawler and same_policy:
            recovery=min(cap,max(base,previous.get('recovery_s',base)*(2 if fresh else 1)))
        interval=request_interval()
        if fresh:interval=max(interval,180 if crawler and seconds is None else 1.0)*(2 if crawler else 1.5)
        until=max(float(previous.get('until',0)),time.time()+recovery)
        if fresh:incident=time.time()
        data={'until':until,'interval_s':interval,'incident_at':incident,'owner':_role,
              'pid':os.getpid(),'recovery_s':recovery,'policy_version':4}
        _write(name,data)
        if fresh:event('lock_incident',interval_s=interval,until=until,recovery_s=recovery)
        return until


def _timestamp(handle):
    handle.seek(0)
    try:return float(handle.read() or 0)
    except ValueError:return 0.0


def _set_timestamp(handle, value):
    handle.seek(0);handle.truncate();handle.write(str(value));handle.flush()


@contextmanager
def slot():
    from .parcels import Blocked, Unavailable
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    with _threads:
        handles=[(DIRECTORY/f'request-{i}.lock').open('a+') for i in range(2)]
        acquired=None
        try:
            while acquired is None:
                if _role == 'crawler' and (not crawler_active() or _read('crawler_lease.json').get('pid') != os.getpid()):
                    raise Unavailable('Crawler lease no longer active')
                observe_api_backoff()
                if cooldown_until()>time.time():raise Blocked()
                # Do not hold the shared rate/HTTP slot locks during a 3+ minute wait.
                with (DIRECTORY/'rate.lock').open('a+') as rate, (DIRECTORY/'crawler_rate.lock').open('a+') as own:
                    fcntl.flock(rate,fcntl.LOCK_EX)
                    current=time.time();last=_timestamp(rate)
                    due=last+request_interval()
                    if _role == 'crawler':due=max(last+request_interval(),_timestamp(own)+request_interval())
                    delay=max(0,due-current)
                    if delay == 0:
                        for handle in handles:
                            try:
                                fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB);acquired=handle;break
                            except BlockingIOError:continue
                        if acquired is not None:
                            _set_timestamp(rate,current)
                            if _role == 'crawler':_set_timestamp(own,current)
                if acquired is None:time.sleep(min(1,max(.05,delay)))
            event('request_start',interval_s=request_interval())
            yield
        finally:
            for handle in handles:handle.close()
