"""Test-session settings applied before any test module imports Prefect.

A developer's own Prefect profile (~/.prefect/profiles.toml, e.g. PREFECT_API_URL pointing at the Compose server) must
not leak into the tests: they would pass only while that server runs. Point Prefect at an empty profiles file so every
flow test uses a temporary local server, exactly as in CI. An explicit PREFECT_API_URL in the environment still wins.
"""

import os
import tempfile
from pathlib import Path

if "PREFECT_API_URL" not in os.environ:
    _profiles = Path(tempfile.mkdtemp(prefix="prefect-test-")) / "profiles.toml"
    os.environ["PREFECT_PROFILES_PATH"] = str(_profiles)
