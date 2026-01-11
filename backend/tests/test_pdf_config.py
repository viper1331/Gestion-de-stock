from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app import app
from backend.core import db, security, services
from backend.core.system_config import get_config, save_config
from backend.services.pdf_config import get_pdf_config_meta, get_pdf_export_config, resolve_pdf_config
from backend.core.pdf_config_models import (
    PdfConfig,
    PdfConfigMeta,
    PdfConfigOverrides,
    PdfHeaderConfig,
    PdfModuleConfig,
)


client = TestClient(app)


def _create_user(username: str, password: str, role: str = "user") -> None:
    services.ensure_database_ready()
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM users WHERE username = ?", (username,))
        conn.execute(
            "INSERT INTO users (username, password, role, is_active) VALUES (?, ?, ?, 1)",
            (username, security.hash_password(password), role),
        )
        conn.commit()


def _login_headers(username: str, password: str) -> dict[str, str]:
    response = client.post(
        "/auth/login",
        json={"username": username, "password": password, "remember_me": False},
    )
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_pdf_config_requires_admin() -> None:
    _create_user("pdfuser", "pdfpass", role="user")
    headers = _login_headers("pdfuser", "pdfpass")
    response = client.get("/admin/pdf-config", headers=headers)
    assert response.status_code == 403

    response = client.post("/admin/pdf-config", headers=headers, json={})
    assert response.status_code == 403

    response = client.get("/admin/pdf-config/preview?module=barcode", headers=headers)
    assert response.status_code == 403


def test_pdf_config_save_and_preview() -> None:
    original = get_config().model_copy(deep=True)
    try:
        headers = _login_headers("admin", "admin123")
        payload = get_pdf_export_config()
        payload.global_config.header = PdfHeaderConfig(enabled=False)
        payload.modules["barcode"] = PdfModuleConfig(override_global=True, config=PdfConfig())
        response = client.post(
            "/admin/pdf-config",
            headers=headers,
            json=payload.model_dump(),
        )
        assert response.status_code == 200
        read_back = client.get("/admin/pdf-config", headers=headers)
        assert read_back.status_code == 200
        preview = client.get("/admin/pdf-config/preview?module=barcode", headers=headers)
        assert preview.status_code == 200
        assert preview.headers["content-type"] == "application/pdf"
    finally:
        save_config(original)


def test_pdf_config_merge_global_preset_module() -> None:
    export_config = get_pdf_export_config()
    export_config.global_config.header = PdfHeaderConfig(enabled=True)
    export_config.presets["Sans en-tête"].config.header = PdfHeaderConfig(enabled=False)
    export_config.modules["barcode"] = PdfModuleConfig(
        override_global=True,
        config=PdfConfig(header=PdfHeaderConfig(enabled=True)),
    )
    resolved = resolve_pdf_config("barcode", preset_name="Sans en-tête", config=export_config)
    assert resolved.config.header.enabled is True


def test_pdf_config_empty_returns_defaults() -> None:
    original = get_config().model_copy(deep=True)
    try:
        system_config = get_config()
        system_config.pdf_exports = None
        save_config(system_config)
        headers = _login_headers("admin", "admin123")
        response = client.get("/admin/pdf-config", headers=headers)
        assert response.status_code == 200
        payload = response.json()
        assert payload["global_config"]["branding"]["logo_enabled"] is True
        assert payload["global_config"]["header"]["enabled"] is True
        assert payload["global_config"]["footer"]["enabled"] is True
        assert payload["global_config"]["theme"]["font_family"] == "Helvetica"
    finally:
        save_config(original)


def test_pdf_config_null_blocks_normalized() -> None:
    original = get_config().model_copy(deep=True)
    try:
        system_config = get_config()
        system_config.pdf_exports = {
            "global_config": {"branding": None, "header": None, "footer": None, "theme": None},
            "modules": {},
            "presets": {},
            "module_meta": {},
        }
        save_config(system_config)
        headers = _login_headers("admin", "admin123")
        response = client.get("/admin/pdf-config", headers=headers)
        assert response.status_code == 200
        payload = response.json()
        assert payload["global_config"]["branding"]["logo_enabled"] is True
        assert payload["global_config"]["header"]["enabled"] is True
        assert payload["global_config"]["footer"]["enabled"] is True
        assert payload["global_config"]["theme"]["font_family"] == "Helvetica"
    finally:
        save_config(original)


def test_pdf_config_module_override_null_does_not_override() -> None:
    export_config = get_pdf_export_config()
    export_config.modules["barcode"] = PdfModuleConfig(
        override_global=True,
        config=PdfConfigOverrides(branding=None),
    )
    resolved = resolve_pdf_config("barcode", config=export_config)
    assert resolved.config.branding.logo_enabled is True


def test_pdf_config_meta_grouping_completeness() -> None:
    export_config = get_pdf_export_config()
    meta = PdfConfigMeta.model_validate(get_pdf_config_meta())
    for key, module in export_config.module_meta.items():
        grouping_meta = meta.module_grouping.get(key)
        assert grouping_meta is not None
        assert module.columns or not grouping_meta.grouping_supported
