"""Registry for UI menu identifiers and constraints."""
from __future__ import annotations

GROUP_IDS: set[str] = {
    "home_group",
    "barcode_group",
    "clothing_group",
    "specialized_group",
    "pharmacy_group",
    "communication_group",
    "operations_group",
    "admin_group",
    "support_group",
}

ITEM_IDS: set[str] = {
    "home",
    "barcode",
    "clothing_dashboard",
    "clothing_reports",
    "clothing_purchase_orders",
    "purchase_suggestions",
    "suppliers",
    "collaborators",
    "dotations",
    "vehicle_inventory",
    "vehicle_qrcodes",
    "remise_inventory",
    "operations_vehicle_qr",
    "operations_pharmacy_links",
    "operations_link_categories",
    "pharmacy",
    "messages",
    "about",
    "settings",
    "admin_settings",
    "system_config",
    "pdf_config",
    "users",
    "permissions",
    "updates",
}

PINNED_IDS: set[str] = {"reload", "logout"}

ALL_MENU_IDS: set[str] = GROUP_IDS | ITEM_IDS | PINNED_IDS
