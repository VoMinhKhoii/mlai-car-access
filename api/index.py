"""Vercel entry point: the FastAPI backend as one Python function (see vercel.json)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.main import app  # noqa: E402,F401
