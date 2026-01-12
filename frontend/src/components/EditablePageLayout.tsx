import { ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { Layout, Responsive, WidthProvider } from "react-grid-layout";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";

import { api } from "../lib/api";
import { useAuth } from "../features/auth/useAuth";
import { useModulePermissions } from "../features/permissions/useModulePermissions";
import { PageBlockCard } from "./PageBlockCard";
import { SafeBlock } from "./SafeBlock";

const ResponsiveGridLayout = WidthProvider(Responsive);

export type EditableLayoutBreakpoint = "lg" | "md" | "sm" | "xs";

export type EditableLayoutSet = Record<EditableLayoutBreakpoint, Layout[]>;

export type EditableLayoutItem = Omit<Layout, "i">;

export type EditablePageBlock = {
  id: string;
  title?: string;
  render: () => ReactNode;
  defaultLayout: Partial<Record<EditableLayoutBreakpoint, EditableLayoutItem>>;
  minH?: number;
  maxH?: number;
  isResizable?: boolean;
  permissions?: string[];
  required?: boolean;
  headerActions?: ReactNode;
  variant?: "card" | "plain";
  bodyClassName?: string;
};

type EditablePageLayoutControls = {
  isEditing: boolean;
  isDirty: boolean;
  editButton: ReactNode;
  actionButtons: ReactNode;
};

type EditablePageLayoutProps = {
  pageKey: string;
  blocks: EditablePageBlock[];
  rightRailBlocks?: EditablePageBlock[];
  renderHeader?: (controls: EditablePageLayoutControls) => ReactNode;
  className?: string;
};

export const LAYOUT_BREAKPOINTS = { lg: 1200, md: 996, sm: 768, xs: 480 } as const;
export const LAYOUT_COLUMNS = { lg: 12, md: 10, sm: 6, xs: 4 } as const;
export const LAYOUT_ROW_HEIGHT = 32;
export const LAYOUT_CONTAINER_PADDING: [number, number] = [16, 16];
export const LAYOUT_MARGIN: [number, number] = [16, 16];
const MIN_LAYOUT_SIZE = 1;

const BREAKPOINTS: EditableLayoutBreakpoint[] = ["lg", "md", "sm", "xs"];

function clampLayoutItem(item: Layout, cols: number): Layout {
  const w = Math.min(cols, Math.max(MIN_LAYOUT_SIZE, Math.floor(item.w ?? cols)));
  const h = Math.max(MIN_LAYOUT_SIZE, Math.floor(item.h ?? MIN_LAYOUT_SIZE));
  let x = Math.max(0, Math.floor(item.x ?? 0));
  let y = Math.max(0, Math.floor(item.y ?? 0));

  if (x + w > cols) {
    x = Math.max(0, cols - w);
  }

  return { ...item, x, y, w, h };
}

function layoutsOverlap(first: Layout, second: Layout): boolean {
  return (
    first.x < second.x + second.w &&
    first.x + first.w > second.x &&
    first.y < second.y + second.h &&
    first.y + first.h > second.y
  );
}

function normalizeLayoutItems(
  items: Layout[],
  cols: number,
  blocksById: Map<string, EditablePageBlock>
): Layout[] {
  const seen = new Set<string>();
  const normalized: Layout[] = [];

  for (const rawItem of items) {
    const id = rawItem.i;
    const block = blocksById.get(id);
    if (!block || seen.has(id)) {
      continue;
    }
    seen.add(id);

    const clamped = clampLayoutItem(rawItem, cols);
    const candidate: Layout = {
      ...clamped,
      i: id,
      minH: block.minH,
      maxH: block.maxH,
      isResizable: block.isResizable
    };

    if (normalized.some((existing) => layoutsOverlap(existing, candidate))) {
      continue;
    }

    normalized.push(candidate);
  }

  return normalized;
}

function normalizeLayouts(
  layouts: EditableLayoutSet,
  blocks: EditablePageBlock[]
): EditableLayoutSet {
  const blocksById = new Map(blocks.map((block) => [block.id, block]));
  const normalized: EditableLayoutSet = { lg: [], md: [], sm: [], xs: [] };

  for (const breakpoint of BREAKPOINTS) {
    const cols = LAYOUT_COLUMNS[breakpoint];
    normalized[breakpoint] = normalizeLayoutItems(layouts[breakpoint] ?? [], cols, blocksById);
  }

  return normalized;
}

function buildDefaultLayouts(blocks: EditablePageBlock[]): EditableLayoutSet {
  const layoutSet: EditableLayoutSet = { lg: [], md: [], sm: [], xs: [] };

  for (const breakpoint of BREAKPOINTS) {
    const cols = LAYOUT_COLUMNS[breakpoint];
    let nextY = 0;

    for (const block of blocks) {
      const fallback: EditableLayoutItem = {
        x: 0,
        y: nextY,
        w: cols,
        h: 8
      };
      const base = block.defaultLayout[breakpoint] ?? fallback;
      const clamped = clampLayoutItem({ ...base, i: block.id }, cols);
      const item: Layout = {
        ...clamped,
        minH: block.minH,
        maxH: block.maxH,
        isResizable: block.isResizable
      };

      layoutSet[breakpoint].push(item);
      nextY = item.y + item.h + 1;
    }
  }

  return normalizeLayouts(layoutSet, blocks);
}

function mergeLayouts(
  defaults: EditableLayoutSet,
  saved: EditableLayoutSet | null,
  blocks: EditablePageBlock[]
): EditableLayoutSet {
  if (!saved) {
    return normalizeLayouts(defaults, blocks);
  }

  const blocksById = new Map(blocks.map((block) => [block.id, block]));
  const merged: EditableLayoutSet = { lg: [], md: [], sm: [], xs: [] };

  for (const breakpoint of BREAKPOINTS) {
    const defaultItems = defaults[breakpoint] ?? [];
    const defaultMap = new Map(defaultItems.map((item) => [item.i, item]));
    const savedItems = saved[breakpoint] ?? [];

    const nextItems = [...defaultItems];

    for (const savedItem of savedItems) {
      if (!blocksById.has(savedItem.i)) {
        continue;
      }
      const base = defaultMap.get(savedItem.i) ?? savedItem;
      const mergedItem: Layout = {
        ...base,
        ...savedItem,
        minH: base.minH,
        maxH: base.maxH,
        isResizable: base.isResizable
      };
      const index = nextItems.findIndex((item) => item.i === savedItem.i);
      if (index >= 0) {
        nextItems[index] = mergedItem;
      } else {
        nextItems.push(mergedItem);
      }
    }

    merged[breakpoint] = nextItems;
  }

  return normalizeLayouts(merged, blocks);
}

function mergeVisibleLayouts(
  previous: EditableLayoutSet,
  next: Partial<Record<EditableLayoutBreakpoint, Layout[]>>,
  hiddenBlockIds: Set<string>
): EditableLayoutSet {
  const merged: EditableLayoutSet = { lg: [], md: [], sm: [], xs: [] };

  for (const breakpoint of BREAKPOINTS) {
    const previousItems = previous[breakpoint] ?? [];
    const nextItems = next[breakpoint] ?? previousItems.filter((item) => !hiddenBlockIds.has(item.i));
    const hiddenItems = previousItems.filter(
      (item) => hiddenBlockIds.has(item.i) && !nextItems.some((visible) => visible.i === item.i)
    );
    merged[breakpoint] = [...nextItems, ...hiddenItems];
  }

  return merged;
}

function areLayoutsEqual(a: EditableLayoutSet, b: EditableLayoutSet): boolean {
  for (const breakpoint of BREAKPOINTS) {
    const normalize = (items: Layout[]) =>
      [...items]
        .map((item) => ({
          i: item.i,
          x: item.x,
          y: item.y,
          w: item.w,
          h: item.h
        }))
        .sort((first, second) => first.i.localeCompare(second.i));
    const aItems = normalize(a[breakpoint] ?? []);
    const bItems = normalize(b[breakpoint] ?? []);
    if (aItems.length !== bItems.length) {
      return false;
    }
    for (let index = 0; index < aItems.length; index += 1) {
      const itemA = aItems[index];
      const itemB = bItems[index];
      if (
        itemA.i !== itemB.i ||
        itemA.x !== itemB.x ||
        itemA.y !== itemB.y ||
        itemA.w !== itemB.w ||
        itemA.h !== itemB.h
      ) {
        return false;
      }
    }
  }
  return true;
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
  pageKey,
  blocks,
  rightRailBlocks = [],
  renderHeader,
  className
}: EditablePageLayoutProps) {
  const { user } = useAuth();
  const permissions = useModulePermissions({ enabled: Boolean(user) });
  const queryClient = useQueryClient();
  const isAdmin = user?.role === "admin";

  const allBlocks = useMemo(() => [...blocks, ...rightRailBlocks], [blocks, rightRailBlocks]);

  const allowedBlocks = useMemo(
    () =>
      allBlocks.filter((block) => {
        if (!block.permissions || block.permissions.length === 0) {
          return true;
        }
        if (isAdmin) {
          return true;
        }
        return block.permissions.some((module) => permissions.canAccess(module));
      }),
    [allBlocks, isAdmin, permissions]
  );

  const requiredBlocks = useMemo(
    () => new Set(allBlocks.filter((block) => block.required).map((block) => block.id)),
    [allBlocks]
  );

  const defaultLayouts = useMemo(() => buildDefaultLayouts(allowedBlocks), [allowedBlocks]);

  const layoutQuery = useQuery({
    queryKey: ["user-layouts", pageKey],
    queryFn: async () => {
      try {
        const response = await api.get<{
          pageKey: string;
          layout: EditableLayoutSet;
          hiddenBlocks: string[];
          updatedAt?: string | null;
        }>(`/user-layouts/${encodeURIComponent(pageKey)}`);
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

  const sanitizedSavedLayouts = useMemo(() => {
    if (!layoutQuery.data?.layout) {
      return null;
    }
    return normalizeLayouts(layoutQuery.data.layout, allowedBlocks);
  }, [allowedBlocks, layoutQuery.data?.layout]);

  const mergedLayouts = useMemo(
    () => mergeLayouts(defaultLayouts, sanitizedSavedLayouts, allowedBlocks),
    [allowedBlocks, defaultLayouts, sanitizedSavedLayouts]
  );

  const mergedHiddenBlocks = useMemo(() => {
    const hidden = layoutQuery.data?.hiddenBlocks ?? [];
    const hiddenSet = new Set(hidden);
    for (const id of requiredBlocks) {
      hiddenSet.delete(id);
    }
    return hiddenSet;
  }, [layoutQuery.data?.hiddenBlocks, requiredBlocks]);

  const [activeLayouts, setActiveLayouts] = useState<EditableLayoutSet>(mergedLayouts);
  const [savedLayouts, setSavedLayouts] = useState<EditableLayoutSet>(mergedLayouts);
  const [hiddenBlocks, setHiddenBlocks] = useState<Set<string>>(mergedHiddenBlocks);
  const [savedHiddenBlocks, setSavedHiddenBlocks] = useState<Set<string>>(mergedHiddenBlocks);
  const [isEditing, setIsEditing] = useState(false);

  useEffect(() => {
    if (!isEditing) {
      setActiveLayouts(mergedLayouts);
      setSavedLayouts(mergedLayouts);
      setHiddenBlocks(new Set(mergedHiddenBlocks));
      setSavedHiddenBlocks(new Set(mergedHiddenBlocks));
    }
  }, [isEditing, mergedLayouts, mergedHiddenBlocks]);

  const isLayoutLoading = layoutQuery.isLoading && !layoutQuery.data;

  const isDirty = useMemo(() => {
    if (!areLayoutsEqual(activeLayouts, savedLayouts)) {
      return true;
    }
    if (hiddenBlocks.size !== savedHiddenBlocks.size) {
      return true;
    }
    for (const id of hiddenBlocks) {
      if (!savedHiddenBlocks.has(id)) {
        return true;
      }
    }
    return false;
  }, [activeLayouts, hiddenBlocks, savedHiddenBlocks, savedLayouts]);

  const saveMutation = useMutation({
    mutationFn: async (payload: { layout: EditableLayoutSet; hiddenBlocks: string[] }) => {
      const response = await api.put(`/user-layouts/${encodeURIComponent(pageKey)}`, payload);
      return response.data;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["user-layouts", pageKey] });
    }
  });

  const canEditLayout = useMemo(
    () => Boolean(user) && allowedBlocks.length > 1,
    [allowedBlocks, user]
  );

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
          const safeLayouts = normalizeLayouts(activeLayouts, allowedBlocks);
          const hiddenIds = Array.from(hiddenBlocks);
          await saveMutation.mutateAsync({ layout: safeLayouts, hiddenBlocks: hiddenIds });
          setActiveLayouts(safeLayouts);
          setSavedLayouts(safeLayouts);
          setSavedHiddenBlocks(new Set(hiddenBlocks));
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
          setHiddenBlocks(new Set(savedHiddenBlocks));
          setIsEditing(false);
        }}
        className="rounded-md border border-slate-700 px-4 py-2 text-sm font-semibold text-slate-200 hover:bg-slate-800"
      >
        Annuler
      </button>
      <button
        type="button"
        onClick={() => {
          const confirmed = window.confirm("Réinitialiser la mise en page ?");
          if (!confirmed) {
            return;
          }
          setActiveLayouts(defaultLayouts);
          setSavedLayouts(defaultLayouts);
          setHiddenBlocks(new Set());
          setSavedHiddenBlocks(new Set());
          setIsEditing(false);
        }}
        className="rounded-md border border-red-500/60 px-4 py-2 text-sm font-semibold text-red-200 hover:bg-red-500/10"
      >
        Réinitialiser
      </button>
    </div>
  ) : null;

  const handleLayoutChange = useCallback(
    (_: Layout[], layouts: Partial<Record<EditableLayoutBreakpoint, Layout[]>>) => {
      setActiveLayouts((prev) => mergeVisibleLayouts(prev, layouts, hiddenBlocks));
    },
    [hiddenBlocks]
  );

  const toggleHidden = useCallback(
    (blockId: string) => {
      if (requiredBlocks.has(blockId)) {
        return;
      }
      setHiddenBlocks((prev) => {
        const next = new Set(prev);
        if (next.has(blockId)) {
          next.delete(blockId);
        } else {
          next.add(blockId);
        }
        return next;
      });
    },
    [requiredBlocks]
  );

  const restoreBlock = useCallback((blockId: string) => {
    setHiddenBlocks((prev) => {
      const next = new Set(prev);
      next.delete(blockId);
      return next;
    });
  }, []);

  const visibleLayouts = useMemo(() => {
    const filtered: EditableLayoutSet = { lg: [], md: [], sm: [], xs: [] };
    for (const breakpoint of BREAKPOINTS) {
      filtered[breakpoint] = activeLayouts[breakpoint].filter((item) => !hiddenBlocks.has(item.i));
    }
    return filtered;
  }, [activeLayouts, hiddenBlocks]);

  const hiddenBlockList = useMemo(
    () => allowedBlocks.filter((block) => hiddenBlocks.has(block.id)),
    [allowedBlocks, hiddenBlocks]
  );

  const sectionClassName = [
    "editable-page",
    "min-h-0",
    "min-w-0",
    "space-y-6",
    "overflow-x-hidden",
    className
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <section className={sectionClassName}>
      {renderHeader ? renderHeader({ isEditing, isDirty, editButton, actionButtons }) : null}
      {isLayoutLoading ? (
        <p className="text-sm text-slate-400">Chargement de la mise en page...</p>
      ) : null}
      <ResponsiveGridLayout
        className="layout min-h-0 min-w-0"
        layouts={visibleLayouts}
        breakpoints={LAYOUT_BREAKPOINTS}
        cols={LAYOUT_COLUMNS}
        rowHeight={LAYOUT_ROW_HEIGHT}
        containerPadding={LAYOUT_CONTAINER_PADDING}
        margin={LAYOUT_MARGIN}
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
          .filter((block) => !hiddenBlocks.has(block.id))
          .map((block) => {
            const header = isEditing ? (
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <span
                    className="layout-drag-handle inline-flex h-7 w-7 cursor-move items-center justify-center rounded border border-slate-700 text-slate-300"
                    title="Déplacer le bloc"
                  >
                    <span className="text-xs">↕</span>
                  </span>
                  <h3 className="text-sm font-semibold text-white">{block.title ?? block.id}</h3>
                </div>
                <button
                  type="button"
                  onClick={() => toggleHidden(block.id)}
                  disabled={block.required}
                  className="inline-flex items-center gap-2 text-xs font-semibold text-slate-200 hover:text-white"
                  title={hiddenBlocks.has(block.id) ? "Afficher ce bloc" : "Masquer ce bloc"}
                >
                  <EyeIcon hidden={hiddenBlocks.has(block.id)} />
                  {hiddenBlocks.has(block.id) ? "Afficher" : "Masquer"}
                </button>
              </div>
            ) : undefined;

            return (
              <PageBlockCard
                key={block.id}
                title={block.title}
                actions={block.headerActions}
                header={header}
                variant={block.variant ?? "card"}
                bodyClassName={block.bodyClassName}
              >
                <SafeBlock>{block.render()}</SafeBlock>
              </PageBlockCard>
            );
          })}
      </ResponsiveGridLayout>
      {isEditing && hiddenBlockList.length > 0 ? (
        <div className="rounded-lg border border-dashed border-slate-700 bg-slate-950/40 p-4">
          <h4 className="text-sm font-semibold text-slate-200">Blocs masqués</h4>
          <ul className="mt-3 space-y-2 text-sm">
            {hiddenBlockList.map((block) => (
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
