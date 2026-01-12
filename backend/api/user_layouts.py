"""Routes pour la personnalisation des mises en page utilisateur."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from backend.api.auth import get_current_user
from backend.core import db, models, services

router = APIRouter()

_DEFAULT_COLUMNS = {"lg": 12, "md": 6, "sm": 1, "xs": 1}

_LAYOUT_RULES: dict[str, dict[str, dict[str, tuple[str, str]] | tuple[str, str]]] = {
    "module:home": {
        "blocks": {"home-main": ("all", "view")},
    },
    "module:barcode": {
        "page_permission": ("barcode", "view"),
        "blocks": {"barcode-main": ("barcode", "view")},
    },
    "module:clothing:inventory": {
        "page_permission": ("clothing", "view"),
        "blocks": {
            "inventory-main": ("clothing", "view"),
            "inventory-orders": ("clothing", "view"),
        },
    },
    "module:clothing:purchase-orders": {
        "page_permission": ("clothing", "view"),
        "blocks": {"purchase-orders-panel": ("clothing", "view")},
    },
    "module:suppliers": {
        "page_permission": ("suppliers", "view"),
        "blocks": {"suppliers-main": ("suppliers", "view")},
    },
    "module:clothing:collaborators": {
        "page_permission": ("dotations", "view"),
        "blocks": {
            "collaborators-table": ("dotations", "view"),
            "collaborators-form": ("dotations", "edit"),
        },
    },
    "module:dotations": {
        "page_permission": ("dotations", "view"),
        "blocks": {"dotations-main": ("dotations", "view")},
    },
    "module:pharmacy:inventory": {
        "page_permission": ("pharmacy", "view"),
        "blocks": {
            "pharmacy-main": ("pharmacy", "view"),
            "pharmacy-lots": ("pharmacy", "view"),
            "pharmacy-orders": ("pharmacy", "view"),
        },
    },
    "module:remise:inventory": {
        "page_permission": ("inventory_remise", "view"),
        "blocks": {
            "remise-inventory-dashboard": ("inventory_remise", "view"),
            "remise-lots": ("inventory_remise", "view"),
        },
    },
    "module:vehicle:inventory": {
        "page_permission": ("vehicle_inventory", "view"),
        "blocks": {
            "vehicle-header": ("vehicle_inventory", "view"),
            "vehicle-list": ("vehicle_inventory", "view"),
            "vehicle-detail": ("vehicle_inventory", "view"),
        },
    },
    "module:vehicle:qrcodes": {
        "page_permission": ("vehicle_qrcodes", "view"),
        "blocks": {"vehicle-qrcodes-main": ("vehicle_qrcodes", "view")},
    },
    "module:reports:clothing": {
        "page_permission": ("clothing", "view"),
        "blocks": {"reports-main": ("clothing", "view")},
    },
    "module:messages": {
        "blocks": {"messages-main": ("all", "view")},
    },
    "module:about": {
        "blocks": {"about-main": ("all", "view")},
    },
    "module:settings": {
        "blocks": {"settings-main": ("all", "view")},
    },
    "module:admin:settings": {
        "page_permission": ("admin", "view"),
        "blocks": {"admin-settings-main": ("admin", "view")},
    },
    "module:system-config": {
        "page_permission": ("admin", "view"),
        "blocks": {"system-config-main": ("admin", "view")},
    },
    "module:pdf:studio": {
        "page_permission": ("admin", "view"),
        "blocks": {"pdf-studio-main": ("admin", "view")},
    },
    "module:users": {
        "page_permission": ("admin", "view"),
        "blocks": {"admin-users-main": ("admin", "view")},
    },
    "module:permissions": {
        "page_permission": ("admin", "view"),
        "blocks": {"permissions-main": ("admin", "view")},
    },
    "module:updates": {
        "page_permission": ("admin", "view"),
        "blocks": {"updates-main": ("admin", "view")},
    },
}


def _resolve_rules(page_key: str) -> dict[str, Any]:
    rules = _LAYOUT_RULES.get(page_key)
    if not rules:
        raise HTTPException(status_code=404, detail="Mise en page introuvable")
    return rules


def _list_permissions(user: models.User) -> dict[str, models.ModulePermission]:
    permission_entries = services.list_module_permissions_for_user(user.id)
    return {entry.module: entry for entry in permission_entries}


def _is_allowed(
    permission_entries: dict[str, models.ModulePermission],
    module: str,
    action: str,
    is_admin: bool,
) -> bool:
    if is_admin:
        return True
    if module == "all":
        return True
    permission = permission_entries.get(module)
    if not permission:
        return False
    return permission.can_edit if action == "edit" else permission.can_view


def _normalize_layouts(layouts: dict[str, list[models.LayoutItem]]) -> dict[str, list[models.LayoutItem]]:
    normalized: dict[str, list[models.LayoutItem]] = {}
    for breakpoint, items in layouts.items():
        cols = _DEFAULT_COLUMNS.get(breakpoint, 1)
        cleaned: list[models.LayoutItem] = []
        for raw in items:
            if raw.w <= 0 or raw.h <= 0:
                continue
            w = max(1, min(cols, int(raw.w)))
            h = max(1, int(raw.h))
            x = max(0, int(raw.x))
            y = max(0, int(raw.y))
            if x + w > cols:
                x = max(0, cols - w)
            candidate = models.LayoutItem(i=raw.i, x=x, y=y, w=w, h=h)
            overlaps = any(
                existing.x < candidate.x + candidate.w
                and existing.x + existing.w > candidate.x
                and existing.y < candidate.y + candidate.h
                and existing.y + existing.h > candidate.y
                for existing in cleaned
            )
            if overlaps:
                continue
            cleaned.append(candidate)
        normalized[breakpoint] = cleaned
    return normalized


def _validate_known_blocks(page_key: str, layout: models.UserPageLayout) -> None:
    rules = _resolve_rules(page_key)
    blocks_rules = rules.get("blocks", {})
    allowed = set(blocks_rules.keys())

    for breakpoint, items in layout.layouts.items():
        for item in items:
            if item.i not in allowed:
                raise HTTPException(status_code=400, detail="Bloc inconnu")

    for block_id in layout.hidden_blocks:
        if block_id not in allowed:
            raise HTTPException(status_code=400, detail="Bloc inconnu")


def _filter_layout_for_user(
    page_key: str, layout: models.UserPageLayout, user: models.User
) -> models.UserPageLayout:
    rules = _resolve_rules(page_key)
    blocks_rules = rules.get("blocks", {})
    page_permission = rules.get("page_permission")
    permissions = _list_permissions(user)
    is_admin = user.role == "admin"

    if page_permission:
        module, action = page_permission
        if not _is_allowed(permissions, module, action, is_admin):
            raise HTTPException(status_code=403, detail="Accès refusé")

    allowed_blocks = {
        block_id
        for block_id, (module, action) in blocks_rules.items()
        if _is_allowed(permissions, module, action, is_admin)
    }
    filtered_layouts: dict[str, list[models.LayoutItem]] = {}
    for breakpoint, items in layout.layouts.items():
        filtered_layouts[breakpoint] = [item for item in items if item.i in allowed_blocks]

    hidden_blocks = [block_id for block_id in layout.hidden_blocks if block_id in allowed_blocks]
    normalized_layouts = _normalize_layouts(filtered_layouts)
    return models.UserPageLayout(
        version=layout.version,
        page_key=layout.page_key,
        layouts=normalized_layouts,
        hidden_blocks=hidden_blocks,
    )


@router.get("/{page_key:path}", response_model=models.UserPageLayout)
async def get_user_layout(
    page_key: str,
    user: models.User = Depends(get_current_user),
)-> models.UserPageLayout:
    _resolve_rules(page_key)
    with db.get_users_connection() as conn:
        row = conn.execute(
            """
            SELECT layout_json, hidden_blocks_json FROM user_page_layouts
            WHERE username = ? AND page_key = ?
            """,
            (user.username, page_key),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Mise en page introuvable")
    try:
        payload = json.loads(row["layout_json"])
        hidden_blocks = json.loads(row["hidden_blocks_json"])
        layout = models.UserPageLayout.model_validate(
            {
                **payload,
                "hidden_blocks": hidden_blocks,
            }
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="Mise en page corrompue") from exc
    if layout.page_key != page_key:
        layout.page_key = page_key
    return _filter_layout_for_user(page_key, layout, user)


@router.put("/{page_key:path}", response_model=models.UserPageLayout)
async def upsert_user_layout(
    page_key: str,
    payload: models.UserPageLayout,
    user: models.User = Depends(get_current_user),
) -> models.UserPageLayout:
    _resolve_rules(page_key)
    if payload.page_key != page_key:
        raise HTTPException(status_code=400, detail="Identifiant de page incohérent")
    _validate_known_blocks(page_key, payload)
    filtered_layout = _filter_layout_for_user(page_key, payload, user)
    layout_json = json.dumps(
        {
            "version": filtered_layout.version,
            "page_key": filtered_layout.page_key,
            "layouts": json.loads(filtered_layout.model_dump_json())["layouts"],
        },
        ensure_ascii=False,
    )
    hidden_json = json.dumps(filtered_layout.hidden_blocks, ensure_ascii=False)
    with db.get_users_connection() as conn:
        conn.execute(
            """
            INSERT INTO user_page_layouts (username, page_key, layout_json, hidden_blocks_json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(username, page_key) DO UPDATE SET
              layout_json = excluded.layout_json,
              hidden_blocks_json = excluded.hidden_blocks_json,
              updated_at = CURRENT_TIMESTAMP
            """,
            (user.username, page_key, layout_json, hidden_json),
        )
    return filtered_layout


@router.delete("/{page_key:path}", status_code=204)
async def delete_user_layout(
    page_key: str,
    user: models.User = Depends(get_current_user),
) -> None:
    with db.get_users_connection() as conn:
        conn.execute(
            "DELETE FROM user_page_layouts WHERE username = ? AND page_key = ?",
            (user.username, page_key),
        )
