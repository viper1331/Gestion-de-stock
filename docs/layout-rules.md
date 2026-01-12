# Layout Rules

These rules prevent regressions in the global editable layout system.

## Do

- Use `EditablePageLayout` on all business pages.
- Define stable block IDs and default layouts for each breakpoint.
- Keep blocks responsive with `min-w-0` containers and `overflow-auto` on table wrappers.
- Ensure only the main content area scrolls (AppLayout), with `min-h-0` on flex parents.
- Use `PageBlockCard` defaults: `min-w-0`, `max-w-full`, `overflow-hidden`, and `flex flex-col` with inner `min-w-0 min-h-0`.

## Avoid

- Fixed widths/min-widths in business pages (`w-[Npx]`, `min-w-[Npx]`, inline `width: 120px`).
- Fixed heights on dynamic lists or tables (`h-[Npx]`), except for media thumbnails.
- Page-specific CSS hacks to force widths.
- Allowing tables to force page-level horizontal scrolling (wrap tables in an overflow container instead).

## Enforcement

Run the guard from the frontend:

```bash
npm -C frontend run lint:layout
```

The guard scans `frontend/src/features/**` and shared business components under `frontend/src/components/**`.
