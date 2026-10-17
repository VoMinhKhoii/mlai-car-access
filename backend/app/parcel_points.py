"""Spatial cache of full polygons returned by official *point* queries, not bulk tiles.

SQLite WAL lets the crawler and API safely reuse surveyed polygons. A point is served
only if it is inside a fetched polygon (never nearest-neighbour extrapolation).
Expiry describes retrieval age; the portal supplies no parcel survey/update date.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

import httpx
from shapely.geometry import Point, mapping, shape

from . import parcels
from .config import CACHE


class ParcelPoints:
    def __init__(self, path: Path | None = None, ttl=86400, *, trust_env=True):
        self.path = path or CACHE / "parcels_points" / "points.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl
        self.local = threading.local()
        self.client = httpx.Client(headers=parcels.HEADERS, timeout=20, trust_env=trust_env,
                                   limits=httpx.Limits(max_connections=2, max_keepalive_connections=2))
        self.stats = {"requests": 0, "polygon_hits": 0, "empty_hits": 0, "lookup_misses": 0, "online_polygon_hits": 0, "online_empty_hits": 0}
        self.guard = threading.Lock()
        db = self.db()
        db.executescript("""
            CREATE TABLE IF NOT EXISTS parcels (
                rowid INTEGER PRIMARY KEY, parcel_id TEXT UNIQUE NOT NULL,
                geometry TEXT NOT NULL, fetched_at REAL NOT NULL);
            CREATE VIRTUAL TABLE IF NOT EXISTS bounds USING rtree(rowid, west, east, south, north);
            CREATE TABLE IF NOT EXISTS empty_points (
                point TEXT PRIMARY KEY, fetched_at REAL NOT NULL);
        """)

    def db(self):
        if not hasattr(self.local, "db"):
            db = sqlite3.connect(self.path, timeout=15)
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA busy_timeout=15000")
            self.local.db = db
        return self.local.db

    def count(self, key):
        with self.guard:
            self.stats[key] += 1

    def lookup(self, lat, lon):
        point, cutoff = Point(lon, lat), time.time() - self.ttl
        rows = self.db().execute("""SELECT p.parcel_id, p.geometry FROM bounds b JOIN parcels p USING(rowid)
            WHERE b.west<=? AND b.east>=? AND b.south<=? AND b.north>=? AND p.fetched_at>=?
            ORDER BY p.fetched_at DESC""", (lon, lon, lat, lat, cutoff))
        for pid, geometry in rows:
            poly = shape(json.loads(geometry))
            if poly.contains(point):
                self.count("polygon_hits")
                return True, {"id": pid, "poly": poly}
        key = f"{lat:.7f},{lon:.7f}"
        if self.db().execute("SELECT 1 FROM empty_points WHERE point=? AND fetched_at>=?", (key, cutoff)).fetchone():
            self.count("empty_hits")
            return True, None
        self.count("lookup_misses")
        return False, None

    def remember(self, lat, lon, result):
        db, now = self.db(), time.time()
        with db:
            if result is None:
                db.execute("INSERT OR REPLACE INTO empty_points VALUES (?,?)", (f"{lat:.7f},{lon:.7f}", now))
            else:
                poly = result["poly"]
                geometry = json.dumps(mapping(poly), separators=(",", ":"))
                # The portal ID can be absent. Geometry identity still cannot merge different parcels.
                import hashlib
                pid = str(result["id"]) if result.get("id") is not None else hashlib.sha256(geometry.encode()).hexdigest()
                db.execute("""INSERT INTO parcels(parcel_id,geometry,fetched_at) VALUES (?,?,?)
                    ON CONFLICT(parcel_id) DO UPDATE SET geometry=excluded.geometry,fetched_at=excluded.fetched_at""",
                           (pid, geometry, now))
                rid = db.execute("SELECT rowid FROM parcels WHERE parcel_id=?", (pid,)).fetchone()[0]
                w, s, e, n = poly.bounds
                db.execute("INSERT OR REPLACE INTO bounds VALUES (?,?,?,?,?)", (rid, w, e, s, n))

    def __call__(self, lat, lon):
        hit, result = self.lookup(lat, lon)
        if hit:
            self.count("online_polygon_hits" if result else "online_empty_hits")
            return result
        self.count("requests")
        result = parcels._parcel(lat, lon, client=self.client)
        if result:
            import hashlib
            pid = str(result["id"]) if result.get("id") is not None else hashlib.sha256(
                json.dumps(mapping(result["poly"]), separators=(",", ":")).encode()).hexdigest()
            result = {**result, "id": pid}
        self.remember(lat, lon, result)
        return result

    def close(self):
        self.client.close()
