"""Token-protected, network-free field kit. Never imports main/agent/portal code."""
from __future__ import annotations

import base64
import binascii
import csv
from datetime import datetime, timezone
from . import fcntl_compat as fcntl
import hmac
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError, model_validator
from shapely.geometry import LineString, Point

from . import evidence, evidence_queue, vehicles
from .config import FRONTEND_DIST, ROOT, STORE, in_hcmc
from .evidence_routes import evidence_queue_get

PHOTO_DIR = STORE / 'field_photos'
COLUMNS = ['osm_way_id', 'alley_name', 'width_m', 'date', 'measured_by', 'note', 'photo_url',
           'submission_id', 'source', 'method', 'lat', 'lon', 'accuracy_m', 'position_note',
           'obstructions', 'turn_space', 'turn_width_m', 'turn_length_m', 'coverage_complete', 'recorded_at']
MAX_PHOTO = 8 * 1024 * 1024


def require_token(authorization: str = Header('')):
    token = os.environ.get('FIELD_TOKEN', '')
    if not token:
        raise HTTPException(503, 'Chưa cấu hình FIELD_TOKEN trên máy chủ.')
    if not hmac.compare_digest(authorization.encode(), ('Bearer '+token).encode()):
        raise HTTPException(401, 'Mã nhóm không đúng hoặc đã đổi.')


router = APIRouter(dependencies=[Depends(require_token)])
page_router = APIRouter()


class Position(BaseModel):
    lat: float = Field(allow_inf_nan=False)
    lon: float = Field(allow_inf_nan=False)

    @model_validator(mode='after')
    def hcmc(self):
        if not in_hcmc(self.lat, self.lon):
            raise ValueError('Vị trí phải trong TP.HCM.')
        return self


class Measurement(Position):
    submission_id: UUID
    way_id: int = Field(gt=0)
    width_m: float = Field(ge=.5, le=15, allow_inf_nan=False)
    method: Literal['tape', 'lidar', 'pacing']
    measured_by: str = Field(min_length=1, max_length=100)
    position_note: str = Field(default='', max_length=500)
    note: str = Field(default='', max_length=1000)
    accuracy_m: float | None = Field(default=None, ge=0, le=10000, allow_inf_nan=False)
    obstructions: list[Literal['steps', 'motorbikes', 'stall']] = Field(default_factory=list, max_length=3)
    turn_space: Literal['yes', 'no', 'unknown'] = 'unknown'
    turn_width_m: float | None = Field(default=None, ge=.5, le=100, allow_inf_nan=False)
    turn_length_m: float | None = Field(default=None, ge=.5, le=100, allow_inf_nan=False)
    coverage_complete: bool = False
    measured_at: datetime | None = None
    photo_base64: str | None = Field(default=None, max_length=4*((MAX_PHOTO+2)//3))

    @model_validator(mode='after')
    def name_present(self):
        self.measured_by = self.measured_by.strip()
        if not self.measured_by:
            raise ValueError('Cần tên người đo.')
        if self.measured_at is not None:
            if self.measured_at.tzinfo is None or self.measured_at.timestamp() > datetime.now(timezone.utc).timestamp()+600:
                raise ValueError('Thời điểm đo cần múi giờ và không nằm trong tương lai.')
        return self


class Arrival(Position):
    submission_id: UUID
    vehicle_id: str = Field(max_length=100)
    result: Literal['in', 'tight', 'no']
    way_ids: list[int] = Field(min_length=1, max_length=30)
    mirrors_folded: bool = False


def inventory():
    data = evidence_queue.read(evidence_queue.INVENTORY)
    if not data.get('ways'):
        raise HTTPException(503, 'Chưa có kho đoạn đường offline. Chuẩn bị evidence_inventory.json trước.')
    return data['ways']


def way_record(wid: int, lat: float, lon: float, ways=None):
    row = (ways if ways is not None else inventory()).get(str(wid))
    if not row or not row.get('coords'):
        raise HTTPException(422, 'Way chưa có trong kho OSM offline.')
    # Require the measurement to lie near the selected geometry, not its midpoint.
    coords = [(x*109400, y*110574) for x,y in row['coords']]
    geom = LineString(coords) if len(coords)>1 else Point(coords[0])
    distance = geom.distance(Point(lon*109400, lat*110574))
    if distance > 150:
        raise HTTPException(422, 'Vị trí cách đoạn đường quá 150 m. Kiểm tra GPS và Way ID.')
    return row, round(distance, 1)


def rows():
    try:
        with evidence.FIELD_FILE.open(encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            return reader.fieldnames or COLUMNS, list(reader)
    except FileNotFoundError:
        return COLUMNS, []


def atomic_csv(row):
    """flock serializes writers across processes; replace keeps readers atomic."""
    path = evidence.FIELD_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        columns, old = rows()
        for existing in old:
            if existing.get('submission_id') == row['submission_id']:
                return existing, False
        columns += [c for c in COLUMNS if c not in columns]
        fd, name = tempfile.mkstemp(prefix='.measurements-', dir=path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                writer.writeheader()
                writer.writerows(old)
                writer.writerow(row)
                f.flush()
                os.fsync(f.fileno())
            os.replace(name, path)
            # Persist the directory entry as well as file contents.
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)
    return row, True


def photo_bytes(encoded):
    if not encoded:
        return None
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(422, 'Ảnh base64 không hợp lệ.')
    if len(raw) > MAX_PHOTO:
        raise HTTPException(413, 'Ảnh tối đa 8 MB.')
    if raw.startswith(b'\xff\xd8\xff'):
        ext = '.jpg'
    elif raw.startswith(b'\x89PNG\r\n\x1a\n'):
        ext = '.png'
    elif raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
        ext = '.webp'
    elif raw[4:8] == b'ftyp' and raw[8:12] in (b'heic', b'heix', b'hevc', b'mif1'):
        ext = '.heic'
    else:
        raise HTTPException(422, 'Chỉ nhận ảnh JPEG, PNG, WebP hoặc HEIC gốc.')
    # Keep original bytes, including EXIF GPS. Do not resize or re-encode.
    return raw, ext


@router.get('/api/field/bootstrap')
def bootstrap():
    campuses = json.loads((ROOT/'docs/eval/hutech-campuses.json').read_text())['campuses']
    profiles = vehicles.all_profiles().values()
    return {'campuses': campuses, 'vehicles': [{'id': p.id, 'label': p.label} for p in profiles if p.kind == 'model']}


@router.get('/api/field/queue')
def field_queue(limit: int = Query(30, ge=1, le=100), bbox: str | None = None):
    evidence.STORE_EVIDENCE.refresh_footprints()
    return evidence_queue_get(limit, bbox, 0)


@router.get('/api/field/snap')
def snap(lat: float, lon: float):
    if not all(math.isfinite(x) for x in (lat,lon)) or not in_hcmc(lat, lon):
        raise HTTPException(422, 'Vị trí phải trong TP.HCM.')
    nearby = []
    for wid, row in inventory().items():
        cs = row.get('coords', [])
        if not cs or not any(abs(y-lat)<.003 and abs(x-lon)<.003 for x,y in cs):
            continue
        if row.get('tags', {}).get('highway') not in ('service','residential','living_street','unclassified','road','footway','path','pedestrian','steps'):
            continue
        try:
            _, distance = way_record(int(wid),lat,lon,{wid: row})
        except HTTPException:
            continue
        nearby.append({'way_id':int(wid),'name':row.get('tags',{}).get('name','Đoạn không tên'),'distance_m':distance})
    nearby.sort(key=lambda r:r['distance_m'])
    return {'items':nearby[:5]}


async def bounded_model(request, model):
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body)>12*1024*1024:
            raise HTTPException(413, 'Bản gửi tối đa 12 MB.')
    try:
        return model.model_validate_json(bytes(body))
    except ValidationError:
        raise HTTPException(422, 'Dữ liệu không hợp lệ. Kiểm tra GPS, Way ID, tên, phương pháp và bề rộng 0,5–15 m.')


@router.post('/api/field/measure')
async def measure(request: Request):
    from starlette.concurrency import run_in_threadpool
    m = await bounded_model(request, Measurement)
    return await run_in_threadpool(save_measurement, m)


def save_measurement(m):
    way, distance = way_record(m.way_id,m.lat,m.lon)
    image = photo_bytes(m.photo_base64)
    photo_url = ''
    if image:
        raw, ext = image
        PHOTO_DIR.mkdir(parents=True, exist_ok=True)
        filename = str(m.submission_id)+ext
        # A retry must not overwrite the original photo or its EXIF.
        try:
            with (PHOTO_DIR/filename).open('xb') as f:
                f.write(raw)
                f.flush()
                os.fsync(f.fileno())
        except FileExistsError:
            pass
        photo_url = '/api/field/photos/'+filename
    method_vi = {'tape':'thước dây','lidar':'LiDAR','pacing':'bước chân'}[m.method]
    recorded_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    row = {'osm_way_id':m.way_id,'alley_name':way.get('tags',{}).get('name',''),
           'width_m':m.width_m,'date':m.measured_at.isoformat(timespec='seconds') if m.measured_at else recorded_at,
           'recorded_at':recorded_at,
           'measured_by':m.measured_by,'note':'; '.join(x for x in [m.note,m.position_note,
             'Vật cản: '+', '.join(m.obstructions) if m.obstructions else ''] if x),
           'photo_url':photo_url,'submission_id':str(m.submission_id),'source':'Nhóm đo hiện trường ('+method_vi+')',
           'method':m.method,'lat':m.lat,'lon':m.lon,'accuracy_m':m.accuracy_m,
           'position_note':m.position_note,'obstructions':','.join(m.obstructions),'turn_space':m.turn_space,
           'turn_width_m':m.turn_width_m,'turn_length_m':m.turn_length_m,
           'coverage_complete':str(m.coverage_complete).lower()}
    recorded, created = atomic_csv(row)
    evidence.STORE_EVIDENCE.reload()
    # plan.area keys widths by store.version; other processes refresh by file stamp.
    return {'ok':True,'created':created,'tier':'Observed' if recorded['method']=='pacing' else 'Measured',
            'recorded':recorded,'distance_m':distance,'evidence_version':evidence.STORE_EVIDENCE.version}


@router.get('/api/field/recent')
def recent(limit: int = Query(20, ge=1, le=100)):
    _, items = rows()
    return {'items':[{**r,'tier':'Observed' if r.get('method')=='pacing' else 'Measured'} for r in items[-limit:][::-1]]}


@router.get('/api/field/photos/{filename}')
def photo(filename: str):
    if Path(filename).name != filename or Path(filename).suffix not in ('.jpg','.png','.webp','.heic'):
        raise HTTPException(404)
    try:
        UUID(Path(filename).stem)
    except ValueError:
        raise HTTPException(404)
    path = PHOTO_DIR/filename
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})


@router.post('/api/field/confirm')
def confirm(c: Arrival):
    try:
        p = vehicles.get_profile(c.vehicle_id)
    except KeyError:
        raise HTTPException(422, 'Mẫu xe không tồn tại.')
    ways = inventory()
    for wid in c.way_ids:
        way_record(wid,c.lat,c.lon,ways)
    rec = {'submission_id':str(c.submission_id),'date':datetime.now(timezone.utc).isoformat(timespec='seconds'),
           'vehicle_id':p.id,'vehicle_label':p.label,'body_width':p.body_width,'mirror_width':p.mirror_width,
           'result':c.result,'way_ids':c.way_ids,'lat':c.lat,'lon':c.lon,'mirrors_folded':c.mirrors_folded}
    path = evidence.CONFIRM_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        lines = path.read_text(encoding='utf-8').splitlines() if path.exists() else []
        for line in lines:
            existing = json.loads(line)
            if existing.get('submission_id') == str(c.submission_id):
                return {'ok':True,'recorded':existing,'tier':'Observed'}
        fd, name = tempfile.mkstemp(prefix='.confirmations-', dir=path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(''.join(line+'\n' for line in lines))
                f.write(json.dumps(rec,ensure_ascii=False)+'\n')
                f.flush()
                os.fsync(f.fileno())
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
    evidence.STORE_EVIDENCE.reload()
    return {'ok':True,'recorded':rec,'tier':'Observed'}


@page_router.get('/field')
@page_router.get('/field/')
def field_page():
    path = FRONTEND_DIST/'field.html'
    if not path.exists():
        raise HTTPException(503, 'Chạy cd frontend && npm run build trước.')
    return FileResponse(path,headers={'Cache-Control':'no-cache'})


@page_router.get('/field-sw.js')
def service_worker():
    return FileResponse(ROOT/'frontend/public/field-sw.js',media_type='application/javascript',
                        headers={'Service-Worker-Allowed':'/','Cache-Control':'no-cache'})


def router_for(app):
    from .crowd_routes import router as crowd_router
    app.include_router(page_router)
    app.include_router(crowd_router)
    return router
