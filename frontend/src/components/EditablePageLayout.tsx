import { ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { Responsive, WidthProvider } from "react-grid-layout";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";

import { api } from "../lib/api";
import { useAuth } from "../features/auth/useAuth";
import { useModulePermissions } from "../features/permissions/useModulePermissions";
import { SafeBlock } from "./SafeBlock";

const ResponsiveGridLayout = WidthProvider(Responsive);

export type EditableLayoutBreakpoint = "lg" | "md" | "sm";

export type EditableLayoutItem = {
  i: string;
  x: number;
  y: number;
  w: number;
  h: number;
  hidden?: boolean;
};

export type EditableLayoutSet = Record<EditableLayoutBreakpoint, EditableLayoutItem[]>;

export type LayoutPermissionRequirement =
  | { module: string; action?: "view" | "edit" }
  | { role: "admin" };

export type EditablePageBlock = {
  id: string;
  title?: string;
  permission?: LayoutPermissionRequirement;
  defaultHidden?: boolean;
  required?: boolean;
  containerClassName?: string;
  render: () => ReactNode;
};

type EditablePageLayoutControls = {
  isEditing: boolean;
  isDirty: boolean;
  editButton: ReactNode;
  actionButtons: ReactNode;
};

type EditablePageLayoutProps = {
  pageId: string;
  blocks: EditablePageBlock[];
  defaultLayouts: EditableLayoutSet;
  pagePermission?: LayoutPermissionRequirement;
  renderHeader?: (controls: EditablePageLayoutControls) => ReactNode;
  className?: string;
};

const DEFAULT_BREAKPOINTS = { lg: 1200, md: 768, sm: 0 } as const;
const DEFAULT_COLUMNS = { lg: 12, md: 6, sm: 1 } as const;
const DEFAULT_ROW_HEIGHT = 32;
const MIN_LAYOUT_WIDTH = 1;
const MIN_LAYOUT_HEIGHT = 4;

function sanitizeLayoutItems(
  items: EditableLayoutItem[],
  cols: number
): { items: EditableLayoutItem[]; isValid: boolean } {
  const seen = new Set<string>();
  const sanitized: EditableLayoutItem[] = [];
  let isValid = true;

  for (const item of items) {
    if (seen.has(item.i)) {
      isValid = false;
      continue;
    }
    if (
      !Number.isFinite(item.x) ||
      !Number.isFinite(item.y) ||
      !Number.isFinite(item.w) ||
      !Number.isFinite(item.h)
    ) {
      isValid = false;
      continue;
    }
    seen.add(item.i);
    const w = Math.min(cols, Math.max(MIN_LAYOUT_WIDTH, Math.floor(item.w)));
    const h = Math.max(MIN_LAYOUT_HEIGHT, Math.floor(item.h));
    let x = Math.max(0, Math.floor(item.x));
    let y = Math.max(0, Math.floor(item.y));

    if (item.x < 0 || item.y < 0 || item.w <= 0 || item.h <= 0 || item.w > cols) {
      isValid = false;
    }

    if (x + w > cols) {
      x = Math.max(0, cols - w);
      isValid = false;
    }

    sanitized.push({ ...item, x, y, w, h });
  }

  for (let index = 0; index < sanitized.length; index += 1) {
    for (let otherIndex = index + 1; otherIndex < sanitized.length; otherIndex += 1) {
      const first = sanitized[index];
      const second = sanitized[otherIndex];
      const overlaps =
        first.x < second.x + second.w &&
        first.x + first.w > second.x &&
        first.y < second.y + second.h &&
        first.y + first.h > second.y;
      if (overlaps) {
        isValid = false;
        break;
      }
    }
    if (!isValid) {
      break;
    }
  }

  return { items: sanitized, isValid };
}

function sanitizeLayouts(
  layouts: EditableLayoutSet,
  fallbackLayouts: EditableLayoutSet
): EditableLayoutSet {
  const breakpoints: EditableLayoutBreakpoint[] = ["lg", "md", "sm"];
  const sanitized: EditableLayoutSet = { lg: [], md: [], sm: [] };

  for (const breakpoint of breakpoints) {
    const cols = DEFAULT_COLUMNS[breakpoint];
    const { items, isValid } = sanitizeLayoutItems(layouts[breakpoint] ?? [], cols);
    if (!isValid) {
      sanitized[breakpoint] = sanitizeLayoutItems(
        fallbackLayouts[breakpoint] ?? [],
        cols
      ).items;
    } else {
      sanitized[breakpoint] = items;
    }
  }

  return sanitized;
}

function normalizeLayouts(
  defaultLayouts: EditableLayoutSet,
  blocks: EditablePageBlock[]
): EditableLayoutSet {
  const breakpoints: EditableLayoutBreakpoint[] = ["lg", "md", "sm"];
  const normalized: EditableLayoutSet = { lg: [], md: [], sm: [] };

  for (const breakpoint of breakpoints) {
    const defaults = defaultLayouts[breakpoint] ?? [];
    const defaultMap = new Map(defaults.map((item) => [item.i, item]));
    const layoutItems: EditableLayoutItem[] = [];

    for (const block of blocks) {
      const isRequired = Boolean(block.required);
      const fallback = defaultMap.get(block.id) ?? {
        i: block.id,
        x: 0,
        y: layoutItems.length * 2,
        w: DEFAULT_COLUMNS[breakpoint],
        h: 8
      };
      layoutItems.push({
        ...fallback,
        i: block.id,
        hidden: isRequired ? false : block.defaultHidden ?? fallback.hidden ?? false
      });
    }
    normalized[breakpoint] = layoutItems;
  }

  return sanitizeLayouts(normalized, normalized);
}

function mergeLayouts(
  defaults: EditableLayoutSet,
  saved: EditableLayoutSet | null,
  blocks: EditablePageBlock[]
): EditableLayoutSet {
  if (!saved) {
    return normalizeLayouts(defaults, blocks);
  }

  const blockMap = new Map(blocks.map((block) => [block.id, block]));
  const requiredBlocks = new Set(blocks.filter((block) => block.required).map((block) => block.id));
  const breakpoints: EditableLayoutBreakpoint[] = ["lg", "md", "sm"];
  const merged: EditableLayoutSet = { lg: [], md: [], sm: [] };

  for (const breakpoint of breakpoints) {
    const defaultItems = defaults[breakpoint] ?? [];
    const defaultMap = new Map(defaultItems.map((item) => [item.i, item]));
    const savedItems = saved[breakpoint] ?? [];
    const savedMap = new Map(savedItems.map((item) => [item.i, item]));
    const nextItems: EditableLayoutItem[] = [];

    for (const [id, savedItem] of savedMap.entries()) {
      if (!blockMap.has(id)) {
        continue;
      }
      const isRequired = requiredBlocks.has(id);
      nextItems.push({
        ...savedItem,
        i: id,
        hidden: isRequired ? false : savedItem.hidden ?? false
      });
    }

    for (const block of blocks) {
      if (nextItems.some((item) => item.i === block.id)) {
        continue;
      }
      const isRequired = Boolean(block.required);
      const defaultItem = defaultMap.get(block.id) ?? {
        i: block.id,
        x: 0,
        y: nextItems.length * 2,
        w: DEFAULT_COLUMNS[breakpoint],
        h: 8
      };
      nextItems.push({
        ...defaultItem,
        i: block.id,
        hidden: isRequired ? false : block.defaultHidden ?? true
      });
    }

    merged[breakpoint] = nextItems;
  }

  return sanitizeLayouts(merged, defaults);
}

function areLayoutsEqual(a: EditableLayoutSet, b: EditableLayoutSet): boolean {
  const breakpoints: EditableLayoutBreakpoint[] = ["lg", "md", "sm"];
  for (const breakpoint of breakpoints) {
    const sortItems = (items: EditableLayoutItem[]) =>
      [...items]
        .map((item) => ({
          i: item.i,
          x: item.x,
          y: item.y,
          w: item.w,
          h: item.h,
          hidden: Boolean(item.hidden)
        }))
        .sort((first, second) => first.i.localeCompare(second.i));
    const normalizedA = sortItems(a[breakpoint] ?? []);
    const normalizedB = sortItems(b[breakpoint] ?? []);
    if (normalizedA.length !== normalizedB.length) {
      return false;
    }
    for (let index = 0; index < normalizedA.length; index += 1) {
      const itemA = normalizedA[index];
      const itemB = normalizedB[index];
      if (
        itemA.i !== itemB.i ||
        itemA.x !== itemB.x ||
        itemA.y !== itemB.y ||
        itemA.w !== itemB.w ||
        itemA.h !== itemB.h ||
        itemA.hidden !== itemB.hidden
      ) {
        return false;
      }
    }
  }
  return true;
}

function mergeVisibleLayouts(
  previous: EditableLayoutSet,
  next: Partial<Record<EditableLayoutBreakpoint, EditableLayoutItem[]>>
): EditableLayoutSet {
  const breakpoints: EditableLayoutBreakpoint[] = ["lg", "md", "sm"];
  const merged: EditableLayoutSet = { lg: [], md: [], sm: [] };

  for (const breakpoint of breakpoints) {
    const previousItems = previous[breakpoint] ?? [];
    const previousMap = new Map(previousItems.map((item) => [item.i, item]));
    const visibleItems = next[breakpoint] ?? previousItems.filter((item) => !item.hidden);
    const nextItems = visibleItems.map((item) => ({
      ...item,
      hidden: previousMap.get(item.i)?.hidden ?? false
    }));

    const hiddenItems = previousItems.filter(
      (item) => item.hidden && !nextItems.some((visible) => visible.i === item.i)
    );

    merged[breakpoint] = [...nextItems, ...hiddenItems];
  }

  return merged;
}

function isBlockAllowed(
  block: EditablePageBlock,
  pagePermission: LayoutPermissionRequirement | undefined,
  canAccess: (module: string, action?: "view" | "edit") => boolean,
  isAdmin: boolean
) {
  const requirement = block.permission ?? pagePermission;
  if (!requirement) {
    return true;
  }
  if ("role" in requirement) {
    return requirement.role === "admin" ? isAdmin : false;
  }
  if (isAdmin) {
    return true;
  }
  return canAccess(requirement.module, requirement.action ?? "view");
}

function EyeIcon({ hidden }: { hidden: boolean }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      className="h-4 w-4"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
    >
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" />
      <circle cx="12" cy="12" r="3" />
      {hidden ? <path d="M3 3l18 18" /> : null}
    </svg>
  );
}

export function EditablePageLayout({
  pageId,
  blocks,
  defaultLayouts,
  pagePermission,
  renderHeader,
  className
}: EditablePageLayoutProps) {
  const { user } = useAuth();
  const permissions = useModulePermissions({ enabled: Boolean(user) });
  const queryClient = useQueryClient();
  const isAdmin = user?.role === "admin";

  const allowedBlocks = useMemo(
    () =>
      blocks.filter((block) =>
        isBlockAllowed(block, pagePermission, permissions.canAccess, Boolean(isAdmin))
      ),
    [blocks, isAdmin, pagePermission, permissions.canAccess]
  );

  const fallbackLayouts = useMemo(
    () => normalizeLayouts(defaultLayouts, allowedBlocks),
    [defaultLayouts, allowedBlocks]
  );

  const layoutQuery = useQuery({
    queryKey: ["ui-layouts", pageId],
    queryFn: async () => {
      try {
        const response = await api.get<{ layouts: EditableLayoutSet }>(
          `/ui/layouts/${encodeURIComponent(pageId)}`
        );
        return response.data;
      } catch (error) {
        if (isAxiosError(error) && error.response?.status === 404) {
          return null;
        }
        throw error;
      }
    },
    enabled: Boolean(user)
  });

  const mergedLayouts = useMemo(
    () => mergeLayouts(fallbackLayouts, layoutQuery.data?.layouts ?? null, allowedBlocks),
    [fallbackLayouts, layoutQuery.data?.layouts, allowedBlocks]
  );

  const canEditLayout = useMemo(() => {
    if (!user) {
      return false;
    }
    if (isAdmin) {
      return true;
    }
    if (!pagePermission || "role" in pagePermission) {
      return Boolean(pagePermission === undefined);
    }
    return permissions.canAccess(pagePermission.module, "edit");
  }, [isAdmin, pagePermission, permissions, user]);

  const [activeLayouts, setActiveLayouts] = useState<EditableLayoutSet>(mergedLayouts);
  const [savedLayouts, setSavedLayouts] = useState<EditableLayoutSet>(mergedLayouts);
  const [isEditing, setIsEditing] = useState(false);

  useEffect(() => {
    if (!isEditing) {
      setActiveLayouts(mergedLayouts);
      setSavedLayouts(mergedLayouts);
    }
  }, [isEditing, mergedLayouts]);

  useEffect(() => {
    if (!canEditLayout && isEditing) {
      setIsEditing(false);
    }
  }, [canEditLayout, isEditing]);

  const isDirty = useMemo(
    () => !areLayoutsEqual(activeLayouts, savedLayouts),
    [activeLayouts, savedLayouts]
  );

  const saveMutation = useMutation({
    mutationFn: async (payload: EditableLayoutSet) => {
      const response = await api.put(`/ui/layouts/${encodeURIComponent(pageId)}`, {
        version: 1,
        page_id: pageId,
        layouts: payload
      });
      return response.data;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["ui-layouts", pageId] });
    }
  });

  const resetMutation = useMutation({
    mutationFn: async () => {
      await api.delete(`/ui/layouts/${encodeURIComponent(pageId)}`);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["ui-layouts", pageId] });
    }
  });

  const handleLayoutChange = useCallback(
    (_: EditableLayoutItem[], layouts: Partial<Record<EditableLayoutBreakpoint, EditableLayoutItem[]>>) => {
      setActiveLayouts((prev) => mergeVisibleLayouts(prev, layouts));
    },
    []
  );

  const requiredBlocks = useMemo(
    () => new Set(blocks.filter((block) => block.required).map((block) => block.id)),
    [blocks]
  );

  const toggleHidden = useCallback((blockId: string) => {
    setActiveLayouts((prev) => {
      if (requiredBlocks.has(blockId)) {
        return prev;
      }
      const next: EditableLayoutSet = { lg: [], md: [], sm: [] };
      (Object.keys(prev) as EditableLayoutBreakpoint[]).forEach((breakpoint) => {
        next[breakpoint] = prev[breakpoint].map((item) =>
          item.i === blockId ? { ...item, hidden: !item.hidden } : item
        );
      });
      return next;
    });
  }, [requiredBlocks]);

  const restoreBlock = useCallback((blockId: string) => {
    setActiveLayouts((prev) => {
      const next: EditableLayoutSet = { lg: [], md: [], sm: [] };
      (Object.keys(prev) as EditableLayoutBreakpoint[]).forEach((breakpoint) => {
        next[breakpoint] = prev[breakpoint].map((item) =>
          item.i === blockId ? { ...item, hidden: false } : item
        );
      });
      return next;
    });
  }, []);

  const editButton = canEditLayout ? (
    <button
      type="button"
      onClick={() => setIsEditing(true)}
      disabled={isEditing}
      className="rounded-md border border-slate-700 px-4 py-2 text-sm font-semibold text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
      title="Personnaliser l'agencement de la page"
    >
      Éditer la page
    </button>
  ) : null;

  const actionButtons = isEditing ? (
    <div className="flex flex-wrap gap-2">
      <button
        type="button"
        onClick={async () => {
          await saveMutation.mutateAsync(activeLayouts);
          setSavedLayouts(activeLayouts);
          setIsEditing(false);
        }}
        disabled={!isDirty || saveMutation.isPending}
        className="rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
      >
        {saveMutation.isPending ? "Enregistrement..." : "Enregistrer"}
      </button>
      <button
        type="button"
        onClick={() => {
          setActiveLayouts(savedLayouts);
          setIsEditing(false);
        }}
        className="rounded-md border border-slate-700 px-4 py-2 text-sm font-semibold text-slate-200 hover:bg-slate-800"
      >
        Annuler
      </button>
      <button
        type="button"
        onClick={async () => {
          const confirmed = window.confirm("Réinitialiser la mise en page ?");
          if (!confirmed) {
            return;
          }
          await resetMutation.mutateAsync();
          setActiveLayouts(fallbackLayouts);
          setSavedLayouts(fallbackLayouts);
        }}
        disabled={resetMutation.isPending}
        className="rounded-md border border-red-500/60 px-4 py-2 text-sm font-semibold text-red-200 hover:bg-red-500/10 disabled:cursor-not-allowed disabled:opacity-70"
      >
        Réinitialiser
      </button>
    </div>
  ) : null;

  const visibleLayouts = useMemo(() => {
    const filtered: EditableLayoutSet = { lg: [], md: [], sm: [] };
    (Object.keys(activeLayouts) as EditableLayoutBreakpoint[]).forEach((breakpoint) => {
      filtered[breakpoint] = activeLayouts[breakpoint].filter((item) => !item.hidden);
    });
    return filtered;
  }, [activeLayouts]);

  const hiddenBlocks = useMemo(() => {
    const hiddenIds = new Set(
      (activeLayouts.lg ?? []).filter((item) => item.hidden).map((item) => item.i)
    );
    return allowedBlocks.filter((block) => hiddenIds.has(block.id));
  }, [activeLayouts.lg, allowedBlocks]);

  const sectionClassName = ["editable-page", "space-y-6", className]
    .filter(Boolean)
    .join(" ");

  if (layoutQuery.isLoading && !layoutQuery.data) {
    return (
      <section className={sectionClassName}>
        {renderHeader ? renderHeader({ isEditing, isDirty, editButton, actionButtons }) : null}
        <p className="text-sm text-slate-400">Chargement de la mise en page...</p>
      </section>
    );
  }

  return (
    <section className={sectionClassName}>
      {renderHeader ? renderHeader({ isEditing, isDirty, editButton, actionButtons }) : null}
      <ResponsiveGridLayout
        className="layout"
        layouts={visibleLayouts}
        breakpoints={DEFAULT_BREAKPOINTS}
        cols={DEFAULT_COLUMNS}
        rowHeight={DEFAULT_ROW_HEIGHT}
        containerPadding={[16, 16]}
        margin={[16, 16]}
        preventCollision
        isBounded
        useCSSTransforms
        measureBeforeMount={false}
        isResizable={isEditing}
        isDraggable={isEditing}
        draggableHandle=".layout-drag-handle"
        onLayoutChange={handleLayoutChange}
        compactType="vertical"
      >
        {allowedBlocks
          .filter((block) => !activeLayouts.lg.find((item) => item.i === block.id)?.hidden)
          .map((block) => {
            const baseClassName =
              block.containerClassName ?? "rounded-lg border border-slate-800 bg-slate-900 p-4";
            const editingClassName = isEditing ? "ring-1 ring-slate-700" : "";
            const containerClassName = [
              "min-w-0 max-w-full h-full",
              baseClassName,
              editingClassName
            ]
              .filter(Boolean)
              .join(" ");
            return (
              <div key={block.id} className={containerClassName}>
                {isEditing ? (
                  <div className="mb-3 flex items-start justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <span
                        className="layout-drag-handle inline-flex h-7 w-7 cursor-move items-center justify-center rounded border border-slate-700 text-slate-300"
                        title="Déplacer le bloc"
                      >
                        <span className="text-xs">↕</span>
                      </span>
                      {block.title ? (
                        <h3 className="text-sm font-semibold text-white">{block.title}</h3>
                      ) : null}
                    </div>
                    <button
                      type="button"
                      onClick={() => toggleHidden(block.id)}
                      disabled={block.required}
                      className="inline-flex items-center gap-2 text-xs font-semibold text-slate-200 hover:text-white"
                      title={
                        activeLayouts.lg.find((item) => item.i === block.id)?.hidden
                          ? "Afficher ce bloc"
                          : "Masquer ce bloc"
                      }
                    >
                      <EyeIcon
                        hidden={Boolean(activeLayouts.lg.find((item) => item.i === block.id)?.hidden)}
                      />
                      {activeLayouts.lg.find((item) => item.i === block.id)?.hidden ? "Afficher" : "Masquer"}
                    </button>
                  </div>
                ) : null}
                <SafeBlock>{block.render()}</SafeBlock>
              </div>
            );
          })}
      </ResponsiveGridLayout>
      {isEditing && hiddenBlocks.length > 0 ? (
        <div className="rounded-lg border border-dashed border-slate-700 bg-slate-950/40 p-4">
          <h4 className="text-sm font-semibold text-slate-200">Blocs masqués</h4>
          <ul className="mt-3 space-y-2 text-sm">
            {hiddenBlocks.map((block) => (
              <li key={block.id} className="flex items-center justify-between">
                <span className="text-slate-300">{block.title ?? block.id}</span>
                <button
                  type="button"
                  onClick={() => restoreBlock(block.id)}
                  className="rounded-md border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200 hover:bg-slate-800"
                >
                  Restaurer
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
