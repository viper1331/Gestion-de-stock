"""Playwright availability helpers for vehicle inventory PDFs."""
from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import platform
from pathlib import Path
import sys
from importlib import metadata

from backend.core.config import settings

logger = logging.getLogger(__name__)

PLAYWRIGHT_OK = "READY"
PLAYWRIGHT_MISSING = "PLAYWRIGHT_MISSING"
BROWSER_MISSING = "BROWSER_MISSING"
RENDERER_HTML = "html"
RENDERER_REPORTLAB = "reportlab"
RENDERER_AUTO = "auto"


@dataclass(frozen=True)
class PlaywrightDiagnostics:
    status: str
    playwright_available: bool
    browser_available: bool
    playwright_version: str | None


def _get_playwright_version() -> str | None:
    try:
        return metadata.version("playwright")
    except metadata.PackageNotFoundError:
        return None


def _chromium_install_hint() -> str:
    return f"{sys.executable} -m playwright install chromium"


def _browser_installed() -> bool:
    if platform.system().lower() == "windows":
        local_appdata = os.environ.get("LOCALAPPDATA")
        if not local_appdata:
            return False
        playwright_root = Path(local_appdata) / "ms-playwright"
        return any(playwright_root.rglob("chrome-headless-shell.exe"))

    playwright_root = Path.home() / ".cache" / "ms-playwright"
    if not playwright_root.exists():
        return False
    return any(playwright_root.rglob("chrome-headless-shell"))


def check_playwright_status() -> PlaywrightDiagnostics:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return PlaywrightDiagnostics(
            status=PLAYWRIGHT_MISSING,
            playwright_available=False,
            browser_available=False,
            playwright_version=None,
        )

    version = _get_playwright_version()
    if not _browser_installed():
        logger.warning(
            "Playwright Chromium not found. Install with: %s",
            _chromium_install_hint(),
        )
        return PlaywrightDiagnostics(
            status=BROWSER_MISSING,
            playwright_available=True,
            browser_available=False,
            playwright_version=version,
        )

    return PlaywrightDiagnostics(
        status=PLAYWRIGHT_OK,
        playwright_available=True,
        browser_available=True,
        playwright_version=version,
    )


def resolve_renderer_mode(diagnostics: PlaywrightDiagnostics) -> str:
    mode = settings.PDF_RENDERER
    if mode == RENDERER_AUTO:
        return RENDERER_HTML if diagnostics.status == PLAYWRIGHT_OK else RENDERER_REPORTLAB
    return mode


def build_playwright_error_message(status: str) -> str:
    if status == PLAYWRIGHT_MISSING:
        return (
            "Playwright n'est pas installé. Installez-le avec : "
            f"{sys.executable} -m pip install playwright"
        )
    if status == BROWSER_MISSING:
        return (
            "Chromium n'est pas installé pour Playwright. Installez-le avec : "
            f"{_chromium_install_hint()}"
        )
    return "Playwright est disponible."


def log_playwright_context(status: str) -> None:
    logger.info("Playwright diagnostics status=%s python=%s", status, sys.executable)


def maybe_install_chromium_on_startup() -> PlaywrightDiagnostics:
    diagnostics = check_playwright_status()
    if diagnostics.status == BROWSER_MISSING:
        log_playwright_context(diagnostics.status)
        logger.warning("Install Playwright Chromium with: %s", _chromium_install_hint())
    return diagnostics


def build_diagnostics_payload() -> dict[str, str | bool | None]:
    diagnostics = check_playwright_status()
    return {
        "renderer_mode": settings.PDF_RENDERER,
        "renderer_active": resolve_renderer_mode(diagnostics),
        "playwright_status": diagnostics.status,
        "playwright_available": diagnostics.playwright_available,
        "browser_available": diagnostics.browser_available,
        "playwright_version": diagnostics.playwright_version,
        "python_executable": sys.executable,
        "os": platform.platform(),
    }
