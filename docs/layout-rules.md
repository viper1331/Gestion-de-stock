# Layout Rules

These rules prevent non-responsive regressions in business pages.

## Responsive Defaults

- Prefer `grid` and `flex` layouts with `min-w-0`.
- Avoid fixed widths; rely on responsive utilities and column layouts.
- Keep scrolling inside tables or panels, not on the whole page.

## Forbidden Patterns

The CI guard rejects the following in `frontend/src/features/**`:

### Fixed Widths

- Tailwind: `w-[Npx]`, `min-w-[Npx]`, `max-w-[Npx]`
- Inline styles: `width`, `minWidth`, `maxWidth` with pixel values

### Fixed Heights on Dynamic Content

- Tailwind: `h-[Npx]` on layout containers

**Allowed exception:** media placeholders (images/iframes). Mark these with the
`allow-fixed-height` class to bypass the guard.

## Practical Tips

- Use `w-full`, `max-w-full`, and `min-w-0` for containers.
- Use `overflow-auto` on table wrappers instead of fixed heights.
- Wrap each business page with `EditablePageLayout` and declare blocks.
