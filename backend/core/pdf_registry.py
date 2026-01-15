"""Registry for PDF Studio modules."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PdfStudioModule:
    key: str
    label: str
    legacy_keys: tuple[str, ...] = ()


PDF_STUDIO_MODULES: tuple[PdfStudioModule, ...] = (
    PdfStudioModule(key="global", label="Global"),
    PdfStudioModule(key="inventory_vehicles", label="Inventaire véhicules", legacy_keys=("vehicle_inventory",)),
    PdfStudioModule(key="inventory_remises", label="Inventaire remises", legacy_keys=("remise_inventory", "inventory_remise")),
    PdfStudioModule(key="inventory_pharmacy", label="Inventaire pharmacie", legacy_keys=("pharmacy",)),
    PdfStudioModule(key="inventory_habillement", label="Inventaire habillement", legacy_keys=("clothing",)),
    PdfStudioModule(key="orders", label="Bons de commande", legacy_keys=("purchase_orders",)),
    PdfStudioModule(key="orders_remises", label="Bons de commande remises", legacy_keys=("remise_orders",)),
    PdfStudioModule(key="orders_pharmacy", label="Bons de commande pharmacie", legacy_keys=("pharmacy_orders",)),
    PdfStudioModule(key="barcodes", label="Codes-barres", legacy_keys=("barcode",)),
)

_MODULE_KEY_MAP: dict[str, str] = {
    module.key: module.key for module in PDF_STUDIO_MODULES
}
for module in PDF_STUDIO_MODULES:
    for legacy_key in module.legacy_keys:
        _MODULE_KEY_MAP.setdefault(legacy_key, module.key)

_LABEL_MAP: dict[str, str] = {module.key: module.label for module in PDF_STUDIO_MODULES}


def normalize_pdf_module_key(key: str) -> str:
    return _MODULE_KEY_MAP.get(key, key)


def is_pdf_module_key(key: str) -> bool:
    return key in _MODULE_KEY_MAP


def pdf_module_label(key: str) -> str:
    canonical = normalize_pdf_module_key(key)
    return _LABEL_MAP.get(canonical, canonical)


def pdf_studio_module_entries() -> list[dict[str, str]]:
    return [{"key": module.key, "label": module.label} for module in PDF_STUDIO_MODULES]
