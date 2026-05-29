"""Pytest fixtures for the service-layer unit-test sweep.

Adds ``backend/`` to ``sys.path`` so ``services.*`` modules import the same way
they do under the running app. Mirrors ``tests/ehr/conftest.py``.
"""
from __future__ import annotations

import sys
from pathlib import Path

# backend/tests/services/conftest.py -> parents[2] == backend/
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))
