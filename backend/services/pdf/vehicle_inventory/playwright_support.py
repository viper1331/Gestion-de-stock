"""Playwright availability helpers for vehicle inventory PDFs."""
from __future__ import annotations

from dataclasses import dataclass
import logging
import platform
import subprocess
import sys
from importlib import metadata

from backend.core.config import settings

logger = logging.getLogger(__name__)

PLAYWRIGHT_OK = "PLAYWRIGHT_OK"
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


def check_playwright_status() -> PlaywrightDiagnostics:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return PlaywrightDiagnostics(
            status=PLAYWRIGHT_MISSING,
            playwright_available=False,
            browser_available=False,
            playwright_version=None,
        )

    version = _get_playwright_version()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            browser.close()
    except Exception as exc:  # pragma: no cover - depends on runtime
        logger.warning("Playwright Chromium launch failed: %s", exc)
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
            f"{sys.executable} -m playwright install chromium"
        )
    return "Playwright est disponible."


def log_playwright_context(status: str) -> None:
    logger.info("Playwright diagnostics status=%s python=%s", status, sys.executable)


def maybe_install_chromium_on_startup() -> PlaywrightDiagnostics:
    diagnostics = check_playwright_status()
    if settings.PDF_RENDERER != RENDERER_AUTO:
        return diagnostics

    if diagnostics.status != BROWSER_MISSING:
        return diagnostics

    log_playwright_context(diagnostics.status)
    install_command = [sys.executable, "-m", "playwright", "install", "chromium"]
    logger.warning(
        "Attempting Playwright Chromium installation with: %s",
        " ".join(install_command),
    )
    try:
        result = subprocess.run(install_command, check=False, capture_output=True, text=True)
    except Exception as exc:
        logger.error("Playwright Chromium installation failed: %s", exc)
        return diagnostics

    if result.returncode == 0:
        logger.warning("Playwright Chromium installation succeeded.")
    else:
        logger.error(
            "Playwright Chromium installation failed (code=%s). stdout=%s stderr=%s",
            result.returncode,
            result.stdout.strip(),
            result.stderr.strip(),
        )

    return check_playwright_status()


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
