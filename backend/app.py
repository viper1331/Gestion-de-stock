"""Application FastAPI principale pour Gestion Stock Pro."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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
    purchase_orders,
    permissions,
    users,
    vehicle_inventory,
    remise_inventory,
)
from backend.core.storage import MEDIA_ROOT
from backend.ws import camera, voice

app = FastAPI(title="Gestion Stock Pro API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
app.include_router(pharmacy_orders.router, prefix="/pharmacy/orders", tags=["pharmacy-purchase-orders"])
app.include_router(vehicle_inventory.router, prefix="/vehicle-inventory", tags=["vehicle-inventory"])
app.include_router(remise_inventory.router, prefix="/remise-inventory", tags=["remise-inventory"])
app.include_router(permissions.router, prefix="/permissions", tags=["permissions"])
app.include_router(users.router, prefix="/users", tags=["users"])

app.mount("/media", StaticFiles(directory=MEDIA_ROOT), name="media")

app.include_router(camera.router, prefix="/ws", tags=["ws-camera"])
app.include_router(voice.router, prefix="/ws", tags=["ws-voice"])


@app.get("/health", tags=["health"])
async def healthcheck() -> dict[str, str]:
    """Renvoie l'état de santé générique du service."""
    return {"status": "ok"}
