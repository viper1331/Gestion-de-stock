# Editable Page Layouts

The application uses a single responsive layout wrapper, `EditablePageLayout`, to ensure that
every business page can be rearranged, hidden, and persisted per user.

## Core Ideas

- **Each page declares blocks** with stable IDs and a default layout.
- **Each page is wrapped in one** `EditablePageLayout` instance.
- **Layouts are responsive** across `lg`, `md`, `sm`, and `xs` breakpoints.
- **Persistence is per user** and stored server-side with a local-cache fallback.

## EditablePageLayout Props

```tsx
<EditablePageLayout
  pageKey="module:clothing:inventory"
  blocks={[{ id: "inventory-main", render: () => <InventoryModule /> }]}
  defaultLayouts={{
    lg: [{ i: "inventory-main", x: 0, y: 0, w: 12, h: 18 }],
    md: [{ i: "inventory-main", x: 0, y: 0, w: 6, h: 18 }],
    sm: [{ i: "inventory-main", x: 0, y: 0, w: 1, h: 18 }],
    xs: [{ i: "inventory-main", x: 0, y: 0, w: 1, h: 18 }]
  }}
/>
```

### Blocks

Each block is declared as:

- `id` (stable identifier for persistence)
- `title` (optional label in edit mode)
- `render` (function returning the block content)
- `permission` (module/role access)
- `defaultHidden` or `required`
- Optional sizing hints (`minH`, `maxH`, `minW`, `maxW`)

## API

The layout API is per-user and is keyed by `pageKey`:

- `GET /user-layouts/:pageKey`
- `PUT /user-layouts/:pageKey`
- `DELETE /user-layouts/:pageKey`

The payload includes `layouts` and `hidden_blocks`. Both are validated server-side to reject
unknown block IDs and normalize layout positions.

## Local Cache

If the server is unreachable, the layout falls back to the most recent local cache entry for
the same `pageKey`.

## Responsive Breakpoints

Breakpoints and column counts are defined centrally in `EditablePageLayout`:

- `lg`, `md`, `sm`, `xs`

Use `min-w-0` and avoid fixed widths to ensure proper reflow.
