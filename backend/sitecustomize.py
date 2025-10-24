"""Custom Python site configuration for local development.

This module is automatically imported by Python (if present on the
``sys.path``) during interpreter start-up. We leverage this hook to make sure
that executing tooling from the ``backend`` directory still allows importing
the top-level :mod:`backend` package.

On Windows, developers often start Uvicorn with ``uvicorn backend.app:app``
while their current working directory is ``Gestion-de-stock/backend``. In
that scenario Python's import machinery cannot resolve ``backend`` because the
parent project directory is missing from ``sys.path``. By inserting the parent
directory here we restore the expected behaviour without affecting other
execution contexts.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_project_root_on_path() -> None:
    """Guarantee that the project root directory is available on ``sys.path``.

    When the interpreter is started from the ``backend`` subdirectory the
    parent project directory (``Gestion-de-stock``) is absent from
    ``sys.path``. Inserting it at the beginning keeps import resolution
    consistent with running commands from the repository root.
    """

    current_dir = Path(__file__).resolve().parent
    project_root = current_dir.parent

    project_root_str = str(project_root)
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)


_ensure_project_root_on_path()

