"""Anonymous crowd ingestion; no automatic trust until agreement/moderation."""
from __future__ import annotations

import base64
from datetime import datetime
import hashlib
import io
import ipaddress
import os
from typing import Literal
from urllib.parse import urlencode, urlsplit, urlunsplit
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field, model_validator

from . import crowd, evidence
from .field_routes import Measurement, bounded_model, inventory, photo_bytes, require_token, snap, way_record, field_page
from .osm import Way

router = APIRouter()
COOKIE = 'ngo_crowd_device'


@router.get('/field/review')
@router.get('/field/qr')
def page():
    return field_page()


def ip_key(request):
    peer = request.client.host if request.client else 'unknown'
    # Only trust the header when explicitly configured behind the local cloudflared process.
    if os.environ.get('FIELD_TRUST_CLOUDFLARED')=='1' and peer in ('127.0.0.1','::1'):
        candidate = request.headers.get('cf-connecting-ip','')
        try: peer = str(ipaddress.ip_address(candidate))
        except ValueError: pass
    return crowd.digest('ip:'+peer)


def device_id(request):
    value = request.cookies.get(COOKIE,'')
    try:
        device, signature = value.split('.')
        UUID(device)
        import hmac
        if hmac.compare_digest(signature,crowd.digest('device:'+device)):
            return crowd.digest('stored-device:'+device)
    except ValueError: pass
    raise HTTPException(401,'Mở lại bước GPS để khởi tạo thiết bị. Không cần đăng nhập.')


@router.post('/api/crowd/session')
def session(request: Request, response: Response):
    crowd.secret()
    try: device_id(request)
    except HTTPException:
        device = str(uuid4())
        value = device+'.'+crowd.digest('device:'+device)
        response.set_cookie(COOKIE,value,max_age=60*60*24*30,httponly=True,samesite='lax',
                            secure=request.url.scheme=='https' or request.headers.get('x-forwarded-proto')=='https')
    return {'ok':True,'limits':{'hour':10,'per_way':3},'photo_required':True}


@router.get('/api/crowd/snap')
def crowd_snap(request: Request, lat: float, lon: float):
    device_id(request)
    data = snap(lat,lon)
    ways = inventory()
    output = []
    for item in data['items']:
        row = ways[str(item['way_id'])]
        w = Way(item['way_id'],row.get('tags',{}),[])
        if w.kind not in ('alley','residential','service','foot'):
            continue
        output.append({**item,'coords':row['coords']})
    return {'items':output}


class CrowdMeasurement(Measurement):
    width_m: float = Field(ge=.8,le=12,allow_inf_nan=False)
    method: Literal['tape','lidar']
    measured_by: str = Field(default='Ẩn danh',max_length=80)
    photo_base64: str = Field(min_length=10,max_length=4*((8*1024*1024+2)//3))
    confirmed_way: Literal[True]
    photo_attestation: Literal[True]
    coverage_complete: Literal[False] = False


def clean_photo(encoded):
    raw, _ = photo_bytes(encoded)
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.width*source.height>20_000_000:
                raise HTTPException(422,'Ảnh tối đa 20 megapixel. Chọn ảnh nhỏ hơn.')
            original = source.getexif()
            keep = Image.Exif()
            # Copy only GPS and capture time; drop make/model/serial/owner/comments.
            if 34853 in original:
                keep[34853] = original.get_ifd(34853)
            if original.get(306): keep[306] = original[306]
            exif_ifd = original.get_ifd(34665) if 34665 in original else {}
            times = {tag:exif_ifd[tag] for tag in (36867,36868,36880,36881,36882) if tag in exif_ifd}
            if times: keep[34665] = times
            image = ImageOps.exif_transpose(source).convert('RGB')
            out = io.BytesIO()
            image.save(out,format='JPEG',quality=90,exif=keep)
            return out.getvalue()
    except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError):
        raise HTTPException(422,'Không đọc được ảnh. Chọn ảnh JPEG/PNG/WebP; với HEIC hãy xuất JPEG tương thích.')


@router.post('/api/crowd/measure')
async def submit(request: Request):
    from starlette.concurrency import run_in_threadpool
    device, ip = device_id(request), ip_key(request)
    value = await bounded_model(request,CrowdMeasurement)
    return await run_in_threadpool(save,value,device,ip)


def save(m,device,ip):
    con = crowd.connect()
    try:
        existing = con.execute('SELECT status,reason,device FROM submissions WHERE id=?',(str(m.submission_id),)).fetchone()
        if existing:
            if existing['device']!=device: raise HTTPException(409,'Mã bản ghi đã dùng trên thiết bị khác.')
            return {'ok':True,'id':str(m.submission_id),'status':existing['status'],'reason':existing['reason']}
    finally: con.close()
    row,_ = way_record(m.way_id,m.lat,m.lon)
    w = Way(m.way_id,row.get('tags',{}),[])
    if w.kind not in ('alley','residential','service','foot'):
        raise HTTPException(422,'Chọn một đoạn hẻm trên bản đồ.')
    crowd.reserve(device,ip,m.way_id)
    raw = clean_photo(m.photo_base64)
    official = crowd.has_official(m.way_id)
    crowd.PHOTOS.mkdir(parents=True,exist_ok=True)
    path = crowd.PHOTOS/(str(m.submission_id)+'.jpg')
    con = crowd.connect()
    try:
        con.execute('BEGIN IMMEDIATE')
        # Enforce lifetime cap again inside the insertion transaction for concurrent requests.
        existing = con.execute('SELECT * FROM submissions WHERE id=?',(str(m.submission_id),)).fetchone()
        if existing:
            if existing['device']!=device: raise HTTPException(409,'Mã bản ghi đã dùng.')
            return {'ok':True,'id':existing['id'],'status':existing['status'],'reason':existing['reason']}
        if con.execute('SELECT count(*) FROM submissions WHERE device=? AND way_id=?',(device,m.way_id)).fetchone()[0]>=3:
            raise HTTPException(429,'Tối đa 3 bản/đoạn/thiết bị.')
        path.write_bytes(raw)
        at = crowd.now().isoformat(timespec='seconds')
        con.execute('''INSERT INTO submissions
        (id,device,ip,way_id,lat,lon,width,method,nickname,photo,photo_hash,measured_at,recorded_at,status,reason)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'pending',?)''',
        (str(m.submission_id),device,ip,m.way_id,m.lat,m.lon,m.width_m,m.method,m.measured_by,
         path.name,hashlib.sha256(raw).hexdigest(),m.measured_at.isoformat() if m.measured_at else at,at,
         'Có Official: cần đồng đội duyệt' if official else 'Chờ đồng đội duyệt hoặc thiết bị độc lập đồng ý'))
        crowd.consensus(con,m.way_id,official)
        result = dict(con.execute('SELECT id,status,reason FROM submissions WHERE id=?',(str(m.submission_id),)).fetchone())
        con.commit()
    finally: con.close()
    evidence.STORE_EVIDENCE.reload()
    return {'ok':True,**result}


@router.get('/api/field/crowd/review',dependencies=[Depends(require_token)])
def review_list():
    items = crowd.records(limit=200)
    return {'items':[{**{k:r[k] for k in ('id','way_id','lat','lon','width','method','nickname','status','reason','recorded_at','reviewer')},
                      'official_bounds':[b.to_json() for b in crowd.official_bounds(r['way_id'])]} for r in items]}


@router.get('/api/field/crowd/photo/{sid}',dependencies=[Depends(require_token)])
def review_photo(sid: UUID):
    path = crowd.PHOTOS/(str(sid)+'.jpg')
    if not path.is_file(): raise HTTPException(404)
    return FileResponse(path,media_type='image/jpeg',headers={'Cache-Control':'private, no-store'})


class Review(BaseModel):
    decision: Literal['approved','rejected']
    reviewer: str = Field(min_length=1,max_length=80)
    note: str = Field(min_length=1,max_length=1000)
    official_override_ack: bool = False

    @model_validator(mode='after')
    def nonempty(self):
        if not self.reviewer.strip() or not self.note.strip():
            raise ValueError('Cần tên người duyệt và kết luận.')
        return self


@router.post('/api/field/crowd/review/{sid}',dependencies=[Depends(require_token)])
def review(sid: UUID, r: Review):
    con = crowd.connect()
    try:
        item = con.execute('SELECT * FROM submissions WHERE id=?',(str(sid),)).fetchone()
        if not item: raise HTTPException(404)
        official = crowd.has_official(item['way_id'])
        if r.decision=='approved' and official and not r.official_override_ack:
            raise HTTPException(422,'Đoạn có Official. Cần xác nhận đã đối chiếu địa chính trước khi duyệt.')
        con.execute('BEGIN IMMEDIATE')
        con.execute('UPDATE submissions SET status=?,reviewer=?,reason=?,reviewed_at=? WHERE id=?',
                    (r.decision,r.reviewer.strip(),r.note.strip(),crowd.now().isoformat(),str(sid)))
        con.execute("UPDATE submissions SET status='pending' WHERE way_id=? AND status='consensus'",(item['way_id'],))
        crowd.consensus(con,item['way_id'],official)
        con.commit()
    finally: con.close()
    evidence.STORE_EVIDENCE.reload()
    return {'ok':True,'status':r.decision}


def public_url():
    raw = os.environ.get('FIELD_PUBLIC_URL','').strip()
    parsed = urlsplit(raw)
    if parsed.scheme not in ('https','http') or not parsed.netloc or parsed.username or parsed.password:
        raise HTTPException(503,'Chưa đặt FIELD_PUBLIC_URL. Chưa có URL công khai để tạo QR.')
    # Always point the stage QR at the anonymous crowd flow, never the review page/token.
    query = {'crowd':'1'}
    return urlunsplit((parsed.scheme,parsed.netloc,'/field',urlencode(query),''))


@router.get('/api/crowd/qr.svg')
def qr():
    import qrcode
    import qrcode.image.svg
    image = qrcode.make(public_url(),image_factory=qrcode.image.svg.SvgPathImage,box_size=12,border=4)
    out = io.BytesIO(); image.save(out)
    return Response(out.getvalue(),media_type='image/svg+xml',headers={'Cache-Control':'no-store'})


@router.get('/api/crowd/stats')
def stats():
    today = crowd.now().astimezone(crowd.VN).date().isoformat()
    items = [r for r in crowd.records(limit=100000) if datetime.fromisoformat(r['recorded_at']).astimezone(crowd.VN).date().isoformat()==today]
    accepted = {r['way_id'] for r in items if r['status'] in ('approved','consensus') and (r['status']=='approved' or not crowd.has_official(r['way_id']))}
    # Use public OSM representative locations, never participants' original GPS/IP/name.
    ways = inventory() if accepted else {}
    points = []
    for wid in sorted(accepted):
        row = ways.get(str(wid),{}); cs = row.get('coords',[])
        if cs:
            x,y = cs[len(cs)//2]; points.append({'way_id':wid,'lat':y,'lon':x})
    try: url = public_url()
    except HTTPException: url = None
    return {'today':today,'measured_alleys':len(accepted),'pending':sum(r['status']=='pending' for r in items),
            'points':points,'public_url':url}
