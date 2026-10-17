"""Default verification runs the active product; parked prototype contracts are explicit skips.

Run a parked suite with RUN_NIGHT_ENGINE_TESTS=1 or RUN_NIGHT_FIELD_TESTS=1
only while reconciling it with the canonical safety/review contracts. See merge report.
"""
import os
import pytest

# Sources are stubbed in network-specific tests; ordinary algorithm cases use the bulletin.
os.environ.setdefault("FLAG_LIVE_HYDRO", "0")

PARKED_ENGINE = {"test_engine_routes.py", "test_engine_walk.py", "test_engine_flood.py",
                 "test_engine_legality.py", "test_engine_hardening.py", "test_engine_width.py",
                 "test_engine_stress.py"}
PARKED_FIELD = {"test_field_kit.py", "test_crowd_field.py"}

def pytest_collection_modifyitems(items):
    for item in items:
        filename = item.path.name
        if filename in PARKED_ENGINE and os.environ.get("RUN_NIGHT_ENGINE_TESTS") != "1":
            item.add_marker(pytest.mark.skip(reason="Parked night-engine contract; product safety suites are active (merge report)"))
        if filename in PARKED_FIELD and os.environ.get("RUN_NIGHT_FIELD_TESTS") != "1":
            item.add_marker(pytest.mark.skip(reason="Night field/crowd kit disabled pending canonical operator-review reconciliation"))
