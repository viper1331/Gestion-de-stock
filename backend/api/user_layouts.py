"""Routes pour la personnalisation des mises en page utilisateur."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException

from backend.api.auth import get_current_user
from backend.core import db, models, services

router = APIRouter()

_BREAKPOINT_COLUMNS = {"lg": 12, "md": 10, "sm": 6, "xs": 4}

_PAGE_RULES: dict[str, dict[str, dict[str, tuple[str, str] | None]]] = {
    "home": {
        "blocks": {
            "home-dashboard": None,
        }
    },
    "module:barcode": {
        "blocks": {
            "barcode-main": ("barcode", "view"),
        }
    },
    "module:clothing:inventory": {
        "blocks": {
            "inventory-main": ("clothing", "view"),
            "inventory-orders": ("clothing", "view"),
            "inventory-stats": ("clothing", "view"),
        }
    },
    "module:clothing:purchase-orders": {
        "blocks": {
            "purchase-orders-panel": ("purchase_orders", "view"),
        }
    },
    "module:purchasing:suggestions": {
        "blocks": {
            "purchase-suggestions-panel": ("purchase_suggestions", "view"),
        }
    },
    "module:reports:clothing": {
        "blocks": {
            "reports-main": ("reports", "view"),
        }
    },
    "module:suppliers": {
        "blocks": {
            "suppliers-main": ("suppliers", "view"),
        }
    },
    "module:clothing:collaborators": {
        "blocks": {
            "collaborators-table": ("collaborators", "view"),
            "collaborators-form": ("collaborators", "edit"),
        }
    },
    "module:dotations": {
        "blocks": {
            "dotations-main": ("dotations", "view"),
        }
    },
    "module:pharmacy:inventory": {
        "blocks": {
            "pharmacy-header": ("pharmacy", "view"),
            "pharmacy-search": ("pharmacy", "view"),
            "pharmacy-items": ("pharmacy", "view"),
            "pharmacy-lots": ("pharmacy", "view"),
            "pharmacy-low-stock": ("pharmacy", "view"),
            "pharmacy-orders": ("pharmacy", "view"),
            "pharmacy-side-panel": ("pharmacy", "view"),
            "pharmacy-categories": ("pharmacy", "view"),
            "pharmacy-stats": ("pharmacy", "view"),
        }
    },
    "module:vehicle:inventory": {
        "blocks": {
            "vehicle-header": ("vehicle_inventory", "view"),
            "vehicle-list": ("vehicle_inventory", "view"),
            "vehicle-detail": ("vehicle_inventory", "view"),
        }
    },
    "module:vehicle:qr": {
        "blocks": {
            "vehicle-qr-main": ("vehicle_qr", "view"),
        }
    },
    "module:vehicle:guide": {
        "blocks": {
            "vehicle-guide-main": ("vehicle_inventory", "view"),
        }
    },
    "module:remise:inventory": {
        "blocks": {
            "remise-header": ("inventory_remise", "view"),
            "remise-filters": ("inventory_remise", "view"),
            "remise-items": ("inventory_remise", "view"),
            "remise-orders": ("inventory_remise", "view"),
            "remise-lots": ("inventory_remise", "view"),
            "remise-stats": ("inventory_remise", "view"),
        }
    },
    "module:settings": {
        "blocks": {
            "settings-main": None,
        }
    },
    "admin:users": {
        "blocks": {
            "admin-users-main": ("__admin__", "role"),
        }
    },
    "admin:permissions": {
        "blocks": {
            "permissions-main": ("__admin__", "role"),
        }
    },
    "system:updates": {
        "blocks": {
            "updates-main": ("__admin__", "role"),
        }
    },
    "admin:settings": {
        "blocks": {
            "admin-settings-main": ("__admin__", "role"),
            "admin-db-settings": ("__admin__", "role"),
        }
    },
    "admin:system-config": {
        "blocks": {
            "system-config-main": ("__admin__", "role"),
        }
    },
    "system:about": {
        "blocks": {
            "about-main": None,
        }
    },
    "system:messages": {
        "blocks": {
            "messages-main": ("messages", "view"),
        }
    },
    "module:pdf:studio": {
        "blocks": {
            "pdf-studio-main": ("__admin__", "role"),
        }
    },
}


def _get_page_rules(page_key: str) -> dict[str, dict[str, tuple[str, str] | None]]:
    rules = _PAGE_RULES.get(page_key)
    if not rules:
        raise HTTPException(status_code=404, detail="Page inconnue")
    return rules["blocks"]


def _load_permissions(user: models.User) -> dict[str, models.ModulePermission]:
    if user.role == "admin":
        return {}
    entries = services.list_module_permissions_for_user(user.id)
    return {entry.module: entry for entry in entries}


def _is_allowed(
    requirement: tuple[str, str] | None,
    user: models.User,
    permissions: dict[str, models.ModulePermission],
) -> bool:
    if requirement is None:
        return True
    module, action = requirement
    if module == "__admin__":
        return user.role == "admin"
    if user.role == "admin":
        return True
    permission = permissions.get(module)
    if not permission:
        return False
    return permission.can_edit if action == "edit" else permission.can_view


def _validate_block_ids(page_key: str, block_ids: set[str]) -> None:
    known_blocks = set(_get_page_rules(page_key).keys())
    unknown = sorted(block_ids - known_blocks)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Blocs inconnus pour {page_key}: {', '.join(unknown)}",
        )


def _normalize_layout(
    layout: dict[str, list[models.PageLayoutItem]],
    allowed_blocks: set[str],
) -> dict[str, list[models.PageLayoutItem]]:
    normalized: dict[str, list[models.PageLayoutItem]] = {}
    for breakpoint, cols in _BREAKPOINT_COLUMNS.items():
        items = layout.get(breakpoint, [])
        normalized_items: list[models.PageLayoutItem] = []
        seen: set[str] = set()
        for item in items:
            if item.i not in allowed_blocks or item.i in seen:
                continue
            seen.add(item.i)
            w = max(1, min(cols, int(item.w)))
            h = max(1, int(item.h))
            x = max(0, int(item.x))
            y = max(0, int(item.y))
            if x + w > cols:
                x = max(0, cols - w)
            candidate = models.PageLayoutItem(i=item.i, x=x, y=y, w=w, h=h)
            overlaps = any(
                candidate.x < existing.x + existing.w
                and candidate.x + candidate.w > existing.x
                and candidate.y < existing.y + existing.h
                and candidate.y + candidate.h > existing.y
                for existing in normalized_items
            )
            if overlaps:
                continue
            normalized_items.append(candidate)
        normalized[breakpoint] = normalized_items
    return normalized


def _serialize_layout(layout: dict[str, list[models.PageLayoutItem]]) -> str:
    return json.dumps(
        {
            breakpoint: [item.model_dump() for item in items]
            for breakpoint, items in layout.items()
        }
    )


@router.get("/{page_key:path}", response_model=models.UserPageLayoutResponse)
async def get_user_layout(
    page_key: str,
    user: models.User = Depends(get_current_user),
) -> models.UserPageLayoutResponse:
    block_rules = _get_page_rules(page_key)
    permissions = _load_permissions(user)
    allowed_blocks = {
        block_id
        for block_id, requirement in block_rules.items()
        if _is_allowed(requirement, user, permissions)
    }

    with db.get_core_connection() as conn:
        row = conn.execute(
            """
            SELECT layout_json, hidden_blocks_json, updated_at
            FROM user_page_layouts
            WHERE username = ? AND page_key = ?
            """,
            (user.username, page_key),
        ).fetchone()

    if row is None:
        return models.UserPageLayoutResponse(
            pageKey=page_key,
            layout={},
            hiddenBlocks=[],
            updatedAt=None,
        )

    try:
        layout_payload = json.loads(row["layout_json"])
        hidden_payload = json.loads(row["hidden_blocks_json"])
        payload = models.UserPageLayoutPayload.model_validate(
            {"layout": layout_payload, "hiddenBlocks": hidden_payload}
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="Mise en page corrompue") from exc

    normalized_layout = _normalize_layout(payload.layout, allowed_blocks)
    normalized_hidden = [block for block in payload.hidden_blocks if block in allowed_blocks]

    return models.UserPageLayoutResponse(
        pageKey=page_key,
        layout=normalized_layout,
        hiddenBlocks=normalized_hidden,
        updatedAt=row["updated_at"],
    )


@router.put("/{page_key:path}", response_model=models.UserPageLayoutResponse)
async def upsert_user_layout(
    page_key: str,
    payload: models.UserPageLayoutPayload,
    user: models.User = Depends(get_current_user),
) -> models.UserPageLayoutResponse:
    block_rules = _get_page_rules(page_key)
    layout_ids = {item.i for items in payload.layout.values() for item in items}
    hidden_ids = set(payload.hidden_blocks)
    _validate_block_ids(page_key, layout_ids | hidden_ids)

    permissions = _load_permissions(user)
    allowed_blocks = {
        block_id
        for block_id, requirement in block_rules.items()
        if _is_allowed(requirement, user, permissions)
    }

    normalized_layout = _normalize_layout(payload.layout, allowed_blocks)
    normalized_hidden = [block for block in payload.hidden_blocks if block in allowed_blocks]

    layout_json = _serialize_layout(normalized_layout)
    hidden_json = json.dumps(normalized_hidden)

    with db.get_core_connection() as conn:
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
        row = conn.execute(
            """
            SELECT updated_at FROM user_page_layouts
            WHERE username = ? AND page_key = ?
            """,
            (user.username, page_key),
        ).fetchone()

    return models.UserPageLayoutResponse(
        pageKey=page_key,
        layout=normalized_layout,
        hiddenBlocks=normalized_hidden,
        updatedAt=row["updated_at"] if row else None,
    )
