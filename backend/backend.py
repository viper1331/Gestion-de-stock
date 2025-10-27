"""Compatibility shim allowing ``import backend`` from inside the package.

When the project is executed from the ``backend`` directory (common on Windows
when running ``uvicorn backend.app:app``) Python attempts to resolve the
``backend`` package relative to that directory. Since there is no nested
``backend`` package the import fails with ``ModuleNotFoundError``. This module
is named ``backend.py`` so that it is picked up by the import machinery in that
scenario. It then masquerades as the actual package by configuring ``__path__``
to point to the directory that holds the real package contents and executing
``__init__.py`` so any package-level side effects are preserved.
"""

from __future__ import annotations

from importlib.machinery import ModuleSpec
from pathlib import Path
import runpy
import sys


_PACKAGE_DIR = Path(__file__).resolve().parent

# Ensure this module behaves like a proper package for submodule lookups
__path__ = [str(_PACKAGE_DIR)]
__file__ = str(_PACKAGE_DIR / "__init__.py")
__package__ = __name__
__spec__ = ModuleSpec(
    name=__name__, loader=None, origin=__file__, is_package=True
)
__spec__.submodule_search_locations = __path__


def _execute_package_initialiser() -> None:
    """Execute the real ``backend/__init__.py`` file in our namespace."""

    init_file = _PACKAGE_DIR / "__init__.py"
    if not init_file.exists():
        return

    # ``runpy.run_path`` executes the file with an isolated globals dict, so we
    # prefer to compile the code manually to keep any symbols it defines in the
    # current module namespace.
    code = compile(init_file.read_text(encoding="utf-8"), str(init_file), "exec")
    exec(code, globals())


_execute_package_initialiser()

# ``runpy`` and ``sys`` are only needed during initialisation; avoid leaking
# them as public attributes of the ``backend`` package.
del runpy, sys, ModuleSpec, Path
