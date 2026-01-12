# Editable Page Layout

This project uses `EditablePageLayout` (react-grid-layout) to provide global, responsive, and user-editable layouts on business pages.

## Key concepts

- **pageKey**: A stable key for the page, used by the backend to store user layouts.
- **blocks**: Declarative blocks for the page. Each block has a stable `id`, default layout values per breakpoint, and a render function.
- **breakpoints**: `lg`, `md`, `sm`, `xs` with centralized column counts in `EditablePageLayout` (`LAYOUT_BREAKPOINTS` + `LAYOUT_COLUMNS`).
- **normalization**: layouts are sanitized on load and before save (clamped sizes/positions, no overlaps, unknown blocks removed).
- **defaults**: default layouts render immediately, even while user layouts are loading.

## Example usage

```tsx
const blocks: EditablePageBlock[] = [
  {
    id: "inventory-main",
    title: "Inventaire",
    permissions: ["clothing"],
    required: true,
    defaultLayout: {
      lg: { x: 0, y: 0, w: 12, h: 18 },
      md: { x: 0, y: 0, w: 10, h: 18 },
      sm: { x: 0, y: 0, w: 6, h: 18 },
      xs: { x: 0, y: 0, w: 4, h: 18 }
    },
    render: () => <InventoryTable />
  }
];

return (
  <EditablePageLayout
    pageKey="module:clothing:inventory"
    blocks={blocks}
    renderHeader={({ editButton, actionButtons, isEditing }) => (
      <div>
        {editButton}
        {isEditing ? actionButtons : null}
      </div>
    )}
  />
);
```

## Notes

- Always use stable block IDs.
- Avoid fixed widths or min-widths inside business pages.
- Edit mode is available on pages with at least two blocks (per user).
- The layout saves per user via `GET /user-layouts/{pageKey}` and `PUT /user-layouts/{pageKey}`.
