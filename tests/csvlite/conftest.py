"""Shared test fixtures for csvlite.

Puts the repo root on ``sys.path`` so ``import csvlite`` works regardless of the
pytest invocation directory (the package lives at the top-level ``csvlite/``).
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
