from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_DEFAULT_KEY = base64.urlsafe_b64encode(b"0" * 32).decode("utf-8")
os.environ.setdefault("TWO_FACTOR_ENCRYPTION_KEY", _DEFAULT_KEY)
