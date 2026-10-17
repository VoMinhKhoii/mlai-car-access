"""Private local crowd ledger, moderation, and conservative evidence adapter."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
from pathlib import Path
import sqlite3

from .config import STORE

DB = STORE/'field_crowd.sqlite'
PHOTOS = STORE/'crowd_photos'
VN = timezone(timedelta(hours=7))


def now():
    return datetime.now(timezone.utc)


def secret():
    value = os.environ.get('FIELD_TOKEN','')
    if not value:
        from fastapi import HTTPException
        raise HTTPException(503,'Máy chủ chưa cấu hình FIELD_TOKEN cho bộ đo và duyệt.')
    return value.encode()


def digest(value):
    return hmac.new(secret(),value.encode(),hashlib.sha256).hexdigest()


def connect():
    DB.parent.mkdir(parents=True,exist_ok=True)
    con = sqlite3.connect(DB, timeout=10)
    con.row_factory = sqlite3.Row
    con.executescript('''
    CREATE TABLE IF NOT EXISTS attempts (device TEXT, ip TEXT, way_id INTEGER, at REAL);
    CREATE INDEX IF NOT EXISTS attempts_at ON attempts(at);
    CREATE TABLE IF NOT EXISTS submissions (
      id TEXT PRIMARY KEY, device TEXT NOT NULL, ip TEXT NOT NULL, way_id INTEGER NOT NULL,
      lat REAL, lon REAL, width REAL, method TEXT, nickname TEXT, photo TEXT, photo_hash TEXT,
      measured_at TEXT, recorded_at TEXT, status TEXT NOT NULL DEFAULT 'pending',
      reason TEXT NOT NULL DEFAULT '', reviewer TEXT NOT NULL DEFAULT '', reviewed_at TEXT);
    CREATE INDEX IF NOT EXISTS crowd_way ON submissions(way_id);
    ''')
    return con


_names_key, _names = None, {}


def way_name(wid):
    global _names_key, _names
    from . import evidence_queue
    key = evidence_queue.stamp(evidence_queue.INVENTORY)
    if key != _names_key:
        _names = {int(k):v.get('tags',{}).get('name','') for k,v in evidence_queue.read(evidence_queue.INVENTORY).get('ways',{}).items()}
        _names_key = key
    return _names.get(wid,'')


def official_bounds(wid, store=None):
    from . import evidence
    from .osm import Way
    if store is None:
        store = evidence.STORE_EVIDENCE
        store.refresh_footprints()
    # Legacy cadastral CSV is keyed by alley name, not always by OSM way id.
    return [b for b in store.bounds_for(Way(wid,{'name':way_name(wid)},[])) if b.tier=='Official']


def has_official(wid):
    return bool(official_bounds(wid))


def reserve(device, ip, wid):
    from fastapi import HTTPException
    con = connect()
    try:
        con.execute('BEGIN IMMEDIATE')
        cutoff = now().timestamp()-3600
        # Keep only aggregate short-lived rate tokens, never raw IP addresses.
        con.execute('DELETE FROM attempts WHERE at < ?', (cutoff,))
        device_n = con.execute('SELECT count(*) FROM attempts WHERE device=?',(device,)).fetchone()[0]
        ip_n = con.execute('SELECT count(*) FROM attempts WHERE ip=?',(ip,)).fetchone()[0]
        way_n = con.execute('SELECT count(*) FROM submissions WHERE device=? AND way_id=?',(device,wid)).fetchone()[0]
        if device_n>=10 or ip_n>=10 or way_n>=3:
            raise HTTPException(429,'Đã đạt giới hạn: 10 lượt/giờ cho thiết bị hoặc IP, tối đa 3 bản/đoạn/thiết bị.',headers={'Retry-After':'3600'})
        con.execute('INSERT INTO attempts VALUES (?,?,?,?)',(device,ip,wid,now().timestamp()))
        con.commit()
    finally:
        con.close()


def consensus(con, wid, official):
    records = con.execute("SELECT * FROM submissions WHERE way_id=? AND status NOT IN ('rejected')",(wid,)).fetchall()
    for a in records:
        if a['status']!='pending':
            continue
        for b in records:
            # Separate server-issued cookies, separate network identities and different images.
            # Shared venue Wi-Fi is deliberately sent for teammate review instead.
            if (a['id']!=b['id'] and a['device']!=b['device'] and a['ip']!=b['ip'] and
                a['photo_hash']!=b['photo_hash'] and abs(a['width']-b['width'])<=.3+1e-8):
                if official:
                    con.execute("UPDATE submissions SET reason='Có Official: cần đồng đội duyệt' WHERE id=? AND status='pending'",(a['id'],))
                else:
                    con.execute("UPDATE submissions SET status='consensus',reason='Hai thiết bị độc lập đồng ý trong 0,3 m' WHERE id=? AND status='pending'",(a['id'],))
                break


def records(status=None, limit=100):
    if not DB.exists(): return []
    con = connect()
    try:
        query = 'SELECT * FROM submissions'
        args = []
        if status: query+=' WHERE status=?'; args.append(status)
        query+=' ORDER BY recorded_at DESC LIMIT ?'; args.append(limit)
        return [dict(r) for r in con.execute(query,args)]
    finally: con.close()


def load_into(store):
    from .evidence import Bound
    if not DB.exists(): return
    grouped = defaultdict(list)
    for row in records(limit=100000):
        wid = row['way_id']
        official = bool(official_bounds(wid,store))
        if row['status']=='approved' or row['status']=='consensus' and not official:
            grouped[wid].append(row)
    for wid, items in grouped.items():
        widths = [r['width'] for r in items]
        # Point observations cap the bottleneck, never guarantee the unseen remainder.
        disagree = max(widths)-min(widths)>.3+1e-8
        hi = max(widths)+.15 if disagree else min(widths)+.15
        reason = 'Các số đo khác nhau quá 0,3 m: giữ khoảng rộng và REVIEW.' if disagree else 'Chưa khảo sát liên tục toàn đoạn.'
        b = Bound(0,hi,'Measured','Đo cộng đồng đã duyệt / đồng thuận',
                  f"{len(items)} số đo {min(widths):g}–{max(widths):g} m; {reason}",
                  observed_on=max(r['measured_at'] for r in items),
                  url='/api/field/crowd/photo/'+items[0]['id'],coverage_complete=False,
                  measurement_schema='crowd-point-width-v1',estimate_m=min(widths))
        b._crowd_review = disagree
        store._add(b,wid)


def mark_review(ranges):
    for wr in ranges.values():
        if any(getattr(b,'_crowd_review',False) for b in wr.evidence):
            wr.review = True
            measured = [b for b in wr.evidence if b.tier=='Measured']
            wr.lo = min(b.lo for b in measured)
            wr.hi = max(b.hi for b in measured)
