"""Application FastAPI principale pour Gestion Stock Pro."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api import (
    auth,
    items,
    categories,
    reports,
    barcode,
    config,
    backup,
    suppliers,
    dotations,
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
    logs,
)
from backend.core.logging_config import configure_logging
from backend.core.storage import MEDIA_ROOT
from backend.services.backup_scheduler import backup_scheduler
from backend.core.system_config import get_effective_cors_origins, rebuild_cors_middleware
from backend.ws import camera, voice


configure_logging()

@asynccontextmanager
async def _lifespan(_: FastAPI):
    await backup_scheduler.start()
    try:
        yield
    finally:
        await backup_scheduler.stop()


app = FastAPI(title="Gestion Stock Pro API", version="2.0.0", lifespan=_lifespan)

app.add_middleware(
    ProxyHeadersMiddleware,
    trusted_hosts="*",
)
rebuild_cors_middleware(app, get_effective_cors_origins())

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(items.router, prefix="/items", tags=["items"])
app.include_router(categories.router, prefix="/categories", tags=["categories"])
app.include_router(reports.router, prefix="/reports", tags=["reports"])
app.include_router(barcode.router, prefix="/barcode", tags=["barcode"])
app.include_router(config.router, prefix="/config", tags=["config"])
app.include_router(backup.router, prefix="/backup", tags=["backup"])
app.include_router(suppliers.router, prefix="/suppliers", tags=["suppliers"])
app.include_router(dotations.router, prefix="/dotations", tags=["dotations"])
app.include_router(pharmacy.router, prefix="/pharmacy", tags=["pharmacy"])
app.include_router(purchase_orders.router, prefix="/purchase-orders", tags=["purchase-orders"])
app.include_router(remise_orders.router, prefix="/remise-inventory/orders", tags=["remise-purchase-orders"])
app.include_router(pharmacy_orders.router, prefix="/pharmacy/orders", tags=["pharmacy-purchase-orders"])
app.include_router(vehicle_inventory.router, prefix="/vehicle-inventory", tags=["vehicle-inventory"])
app.include_router(remise_inventory.router, prefix="/remise-inventory", tags=["remise-inventory"])
app.include_router(permissions.router, prefix="/permissions", tags=["permissions"])
app.include_router(users.router, prefix="/users", tags=["users"])
app.include_router(updates.router, prefix="/updates", tags=["updates"])
app.include_router(system_config_api.router, prefix="/system", tags=["system"])
app.include_router(about.router, prefix="/about", tags=["about"])
app.include_router(logs.router, prefix="/logs", tags=["logs"])

app.mount("/media", StaticFiles(directory=MEDIA_ROOT), name="media")

app.include_router(camera.router, prefix="/ws", tags=["ws-camera"])
app.include_router(voice.router, prefix="/ws", tags=["ws-voice"])

@app.get("/health", tags=["health"])
async def healthcheck() -> dict[str, str]:
    """Renvoie l'état de santé générique du service."""
    return {"status": "ok"}
