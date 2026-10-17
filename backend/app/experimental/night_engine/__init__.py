"""Superseded engine preserved for reconciliation; no production route imports it."""
import os
if os.environ.get("ENABLE_NIGHT_ENGINE") != "1":
    raise RuntimeError("Night engine is parked; use app.plan (product safety engine)")
