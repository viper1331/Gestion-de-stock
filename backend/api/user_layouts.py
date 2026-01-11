"""Routes pour la personnalisation des mises en page utilisateur."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException

from backend.api.auth import get_current_user
from backend.core import db, models, services

router = APIRouter()

_LAYOUT_RULES: dict[str, dict[str, dict[str, tuple[str, str]] | tuple[str, str]]] = {
    "module:clothing:inventory": {
        "page_permission": ("clothing", "view"),
        "blocks": {
            "inventory-main": ("clothing", "view"),
            "inventory-orders": ("clothing", "view"),
        },
    },
    "module:clothing:collaborators": {
        "page_permission": ("dotations", "view"),
        "blocks": {
            "collaborators-table": ("dotations", "view"),
            "collaborators-form": ("dotations", "edit"),
        },
    },
    "module:clothing:purchase-orders": {
        "page_permission": ("clothing", "view"),
        "blocks": {
            "purchase-orders-panel": ("clothing", "view"),
        },
    },
}


def _filter_layout_for_user(
    page_id: str, layout: models.UserLayout, user: models.User
) -> models.UserLayout:
    rules = _LAYOUT_RULES.get(page_id)
    if not rules:
        return layout

    blocks_rules = rules.get("blocks", {})
    if user.role == "admin":
        filtered_layouts = {
            breakpoint: [item for item in items if item.i in blocks_rules]
            for breakpoint, items in layout.layouts.items()
        }
        return models.UserLayout(
            version=layout.version, page_id=layout.page_id, layouts=filtered_layouts
        )

    permission_entries = services.list_module_permissions_for_user(user.id)
    permissions = {entry.module: entry for entry in permission_entries}

    def is_allowed(module: str, action: str) -> bool:
        permission = permissions.get(module)
        if not permission:
            return False
        return permission.can_edit if action == "edit" else permission.can_view

    filtered_layouts: dict[str, list[models.LayoutItem]] = {}
    for breakpoint, items in layout.layouts.items():
        filtered_items: list[models.LayoutItem] = []
        for item in items:
            requirement = blocks_rules.get(item.i)
            if not requirement:
                continue
            module, action = requirement
            if is_allowed(module, action):
                filtered_items.append(item)
        filtered_layouts[breakpoint] = filtered_items

    return models.UserLayout(version=layout.version, page_id=layout.page_id, layouts=filtered_layouts)


@router.get("/{page_id:path}", response_model=models.UserLayout)
async def get_user_layout(
    page_id: str,
    user: models.User = Depends(get_current_user),
) -> models.UserLayout:
    with db.get_users_connection() as conn:
        row = conn.execute(
            """
            SELECT layout_json FROM user_layouts
            WHERE username = ? AND page_id = ?
            """,
            (user.username, page_id),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Mise en page introuvable")
    try:
        payload = json.loads(row["layout_json"])
        layout = models.UserLayout.model_validate(payload)
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="Mise en page corrompue") from exc
    if layout.page_id != page_id:
        layout.page_id = page_id
    return _filter_layout_for_user(page_id, layout, user)


@router.put("/{page_id:path}", response_model=models.UserLayout)
async def upsert_user_layout(
    page_id: str,
    payload: models.UserLayout,
    user: models.User = Depends(get_current_user),
) -> models.UserLayout:
    if payload.page_id != page_id:
        raise HTTPException(status_code=400, detail="Identifiant de page incohérent")
    filtered_layout = _filter_layout_for_user(page_id, payload, user)
    layout_json = filtered_layout.model_dump_json()
    with db.get_users_connection() as conn:
        conn.execute(
            """
            INSERT INTO user_layouts (username, page_id, layout_json)
            VALUES (?, ?, ?)
            ON CONFLICT(username, page_id) DO UPDATE SET
              layout_json = excluded.layout_json,
              updated_at = CURRENT_TIMESTAMP
            """,
            (user.username, page_id, layout_json),
        )
    return filtered_layout


@router.delete("/{page_id:path}", status_code=204)
async def delete_user_layout(
    page_id: str,
    user: models.User = Depends(get_current_user),
) -> None:
    with db.get_users_connection() as conn:
        conn.execute(
            "DELETE FROM user_layouts WHERE username = ? AND page_id = ?",
            (user.username, page_id),
        )
