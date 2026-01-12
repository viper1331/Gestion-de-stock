# Layout rules: responsive blocks only

EditablePageLayout relies on responsive sizing rules. Fixed widths break the grid,
create horizontal scrollbars, and cause blocks to overlap. Business pages must
follow these guidelines.

## ✅ Allowed

- `w-full`, `max-w-full`, `min-w-0`
- Responsive utilities (`sm:`, `md:`, `lg:`)
- Flex/grid sizing (`flex-1`, `basis-*`, `grid-cols-*`)
- Truncation/wrapping to handle long content (`truncate`, `break-words`)

## ❌ Forbidden (business pages)

- Tailwind fixed widths:
  - `w-[Npx]`
  - `min-w-[Npx]`
  - `max-w-[Npx]`
- Inline styles with fixed widths:
  - `style={{ width: 320 }}`
  - `style={{ minWidth: "320px" }}`

## Why this matters

Fixed widths force child content to escape its grid cell and generate horizontal
overflow. EditablePageLayout depends on blocks shrinking and growing inside the
react-grid-layout columns.

## Examples

### ✅ Good

```tsx
<div className="min-w-0 w-full">
  <table className="w-full table-fixed">
    ...
  </table>
</div>
```

### ❌ Bad

```tsx
<div className="w-[320px]">
  ...
</div>
```

If you must use a fixed width, document it explicitly and keep the exception rare.
