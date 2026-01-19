"""Application FastAPI principale pour Gestion Stock Pro."""
from contextlib import asynccontextmanager
import logging
import sqlite3

from fastapi import FastAPI
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api import (
    auth,
    admin,
    items,
    categories,
    reports,
    barcode,
    config,
    backup,
    suppliers,
    dotations,
    item_links,
    link_categories,
    pharmacy,
    pharmacy_orders,
    remise_orders,
    purchase_orders,
    permissions,
    updates,
    users,
    vehicle_inventory,
    remise_inventory,
    about,
    system_config as system_config_api,
    pdf_config as pdf_config_api,
    pdf_studio as pdf_studio_api,
    logs,
    messages,
    user_layouts,
    sites as sites_api,
    ui_menu,
)
from backend.api.site_context import SiteContextMiddleware
from backend.core.logging_config import (
    LOG_BACKUP_COUNT,
    LOG_DIR,
    configure_logging,
    purge_rotated_logs,
)
from backend.core.env_loader import load_env
from backend.core.services import (
    _ensure_vehicle_pharmacy_templates,
    ensure_database_ready,
    ensure_password_reset_configured,
)
from backend.core import two_factor_crypto
from backend.core.storage import MEDIA_ROOT
from backend.services.backup_scheduler import backup_scheduler
from backend.services import notifications
from backend.services.pdf.vehicle_inventory.playwright_support import (
    PLAYWRIGHT_OK,
    maybe_install_chromium_on_startup,
)
from backend.core.system_config import get_effective_cors_origins, rebuild_cors_middleware
from backend.ws import camera, voice

load_env()
configure_logging()
logger = logging.getLogger(__name__)

@asynccontextmanager
async def _lifespan(app: FastAPI):
    try:
        purge_rotated_logs(LOG_DIR, LOG_BACKUP_COUNT, logger)
        ensure_database_ready()
        two_factor_crypto.ensure_configured()
        ensure_password_reset_configured()
        _ensure_vehicle_pharmacy_templates()
        notifications.ensure_email_delivery_ready()
        notifications.purge_email_tables()
    except sqlite3.IntegrityError:
        if logger:
            logger.warning("Vehicle pharmacy templates already exist; skipping seed.")
    except Exception as exc:
        logger.error("Database initialization failed during startup.", exc_info=exc)
        raise
    diagnostics = maybe_install_chromium_on_startup()
    if diagnostics.status != PLAYWRIGHT_OK:
        logger.warning(
            "Playwright diagnostics at startup: status=%s", diagnostics.status
        )
    await backup_scheduler.reload_from_db()
    await backup_scheduler.start()
    notifications.start_outbox_worker(app)
    try:
        yield
    finally:
        await backup_scheduler.stop()
        await notifications.shutdown_outbox_worker(app)


app = FastAPI(title="Gestion Stock Pro API", version="2.0.0", lifespan=_lifespan)

app.add_middleware(
    ProxyHeadersMiddleware,
    trusted_hosts="*",
)
app.add_middleware(SiteContextMiddleware)
rebuild_cors_middleware(app, get_effective_cors_origins())

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])
app.include_router(items.router, prefix="/items", tags=["items"])
app.include_router(categories.router, prefix="/categories", tags=["categories"])
app.include_router(reports.router, prefix="/reports", tags=["reports"])
app.include_router(barcode.router, prefix="/barcode", tags=["barcode"])
app.include_router(barcode.router, prefix="/barcodes", tags=["barcode"], include_in_schema=False)
app.include_router(config.router, prefix="/config", tags=["config"])
app.include_router(backup.router, prefix="/backup", tags=["backup"])
app.include_router(suppliers.router, prefix="/suppliers", tags=["suppliers"])
app.include_router(dotations.router, prefix="/dotations", tags=["dotations"])
app.include_router(pharmacy.router, prefix="/pharmacy", tags=["pharmacy"])
app.include_router(purchase_orders.router, prefix="/purchase-orders", tags=["purchase-orders"])
app.include_router(remise_orders.router, prefix="/remise-inventory/orders", tags=["remise-purchase-orders"])
app.include_router(pharmacy_orders.router, prefix="/pharmacy/orders", tags=["pharmacy-purchase-orders"])
app.include_router(vehicle_inventory.router, prefix="/vehicle-inventory", tags=["vehicle-inventory"])
app.include_router(item_links.router, tags=["item-links"])
app.include_router(link_categories.router, prefix="/link-categories", tags=["link-categories"])
app.include_router(remise_inventory.router, prefix="/remise-inventory", tags=["remise-inventory"])
app.include_router(permissions.router, prefix="/permissions", tags=["permissions"])
app.include_router(users.router, prefix="/users", tags=["users"])
app.include_router(updates.router, prefix="/updates", tags=["updates"])
app.include_router(system_config_api.router, prefix="/system", tags=["system"])
app.include_router(pdf_config_api.router, prefix="/admin", tags=["pdf-config"])
app.include_router(pdf_studio_api.router, tags=["pdf-studio"])
app.include_router(about.router, prefix="/about", tags=["about"])
app.include_router(logs.router, prefix="/logs", tags=["logs"])
app.include_router(messages.router, prefix="/messages", tags=["messages"])
app.include_router(user_layouts.router, prefix="/user-layouts", tags=["user-layouts"])
app.include_router(user_layouts.router, prefix="/ui/layouts", tags=["user-layouts"])
app.include_router(ui_menu.router, prefix="/ui", tags=["ui"])
app.include_router(sites_api.router, prefix="/sites", tags=["sites"])

app.mount("/media", StaticFiles(directory=MEDIA_ROOT), name="media")

app.include_router(camera.router, prefix="/ws", tags=["ws-camera"])
app.include_router(voice.router, prefix="/ws", tags=["ws-voice"])

@app.get("/health", tags=["health"])
async def healthcheck() -> dict[str, str]:
    """Renvoie l'état de santé générique du service."""
    return {"status": "ok"}
