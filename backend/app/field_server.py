"""Field-only public surface. Run on loopback:8790; tunnel only this process."""
import os
from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles

from .config import FRONTEND_DIST
from .field_routes import confirm, field_queue, require_token, router_for

app = FastAPI(title='Ngõ Ngách · Bộ đo hiện trường', docs_url=None, redoc_url=None, openapi_url=None)
if os.environ.get("ENABLE_NIGHT_FIELD_KIT") == "1":
    app.include_router(router_for(app))
# Same Arrival Confirmation contract/path as the main app, with token + validation.
if os.environ.get('ENABLE_NIGHT_FIELD_KIT') == '1':
    app.add_api_route('/api/confirm', confirm, methods=['POST'], dependencies=[Depends(require_token)])
if os.environ.get('ENABLE_NIGHT_FIELD_KIT') == '1':
    app.add_api_route('/api/evidence/queue', field_queue, methods=['GET'], dependencies=[Depends(require_token)])
if (FRONTEND_DIST/'assets').is_dir():
    app.mount('/assets', StaticFiles(directory=FRONTEND_DIST/'assets'), name='field-assets')
