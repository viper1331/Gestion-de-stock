import { ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { Responsive, WidthProvider } from "react-grid-layout";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";

import { api } from "../lib/api";
import { useAuth } from "../features/auth/useAuth";
import { useModulePermissions } from "../features/permissions/useModulePermissions";
import { SafeBlock } from "./SafeBlock";

const ResponsiveGridLayout = WidthProvider(Responsive);

export type EditableLayoutBreakpoint = "lg" | "md" | "sm" | "xs";

export type EditableLayoutItem = {
  i: string;
  x: number;
  y: number;
  w: number;
  h: number;
  minW?: number;
  maxW?: number;
  minH?: number;
  maxH?: number;
  isResizable?: boolean;
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
  minW?: number;
  maxW?: number;
  minH?: number;
  maxH?: number;
  isResizable?: boolean;
  defaultLayout?: Partial<Record<EditableLayoutBreakpoint, EditableLayoutItem>>;
  render: () => ReactNode;
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
  defaultLayouts: EditableLayoutSet;
  pagePermission?: LayoutPermissionRequirement;
  renderHeader?: (controls: EditablePageLayoutControls) => ReactNode;
  className?: string;
  fullWidthBlocks?: string[];
  sidePanelBlocks?: string[];
};

const DEFAULT_BREAKPOINTS = { lg: 1280, md: 960, sm: 640, xs: 0 } as const;
const DEFAULT_COLUMNS = { lg: 12, md: 6, sm: 1, xs: 1 } as const;
const DEFAULT_ROW_HEIGHT = 32;
const MIN_LAYOUT_WIDTH = 1;
const MIN_LAYOUT_HEIGHT = 4;
const AUTO_SAVE_DELAY = 1500;

type LayoutCachePayload = {
  layouts: EditableLayoutSet;
  hiddenBlocks: string[];
};

function getLayoutCacheKey(pageKey: string) {
  return `gsp/layouts/${pageKey}`;
}

function readLayoutCache(pageKey: string): LayoutCachePayload | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    const raw = window.localStorage.getItem(getLayoutCacheKey(pageKey));
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as LayoutCachePayload;
    if (!parsed || typeof parsed !== "object") {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

function writeLayoutCache(pageKey: string, payload: LayoutCachePayload) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(getLayoutCacheKey(pageKey), JSON.stringify(payload));
  } catch {
    // Ignore cache write failures.
  }
}

function getDefaultHiddenBlocks(blocks: EditablePageBlock[]) {
  return blocks
    .filter((block) => !block.required && block.defaultHidden)
    .map((block) => block.id);
}

function mergeHiddenBlocks(
  blocks: EditablePageBlock[],
  savedHidden: string[] | null
): string[] {
  const required = new Set(blocks.filter((block) => block.required).map((block) => block.id));
  const hidden = new Set(savedHidden ?? getDefaultHiddenBlocks(blocks));
  required.forEach((id) => hidden.delete(id));
  return Array.from(hidden);
}

function applyBlockConstraints(
  layouts: EditableLayoutSet,
  blocks: EditablePageBlock[]
): EditableLayoutSet {
  const blockMap = new Map(blocks.map((block) => [block.id, block]));
  const breakpoints: EditableLayoutBreakpoint[] = ["lg", "md", "sm", "xs"];
  const constrained: EditableLayoutSet = { lg: [], md: [], sm: [], xs: [] };

  for (const breakpoint of breakpoints) {
    constrained[breakpoint] = (layouts[breakpoint] ?? []).map((item) => {
      const block = blockMap.get(item.i);
      if (!block) {
        return item;
      }
      return {
        ...item,
        minW: block.minW,
        maxW: block.maxW,
        minH: block.minH,
        maxH: block.maxH,
        isResizable: block.isResizable
      };
    });
  }

  return constrained;
}

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
  const breakpoints: EditableLayoutBreakpoint[] = ["lg", "md", "sm", "xs"];
  const sanitized: EditableLayoutSet = { lg: [], md: [], sm: [], xs: [] };

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
  blocks: EditablePageBlock[],
  fullWidthBlocks: string[],
  sidePanelBlocks: string[]
): EditableLayoutSet {
  const breakpoints: EditableLayoutBreakpoint[] = ["lg", "md", "sm", "xs"];
  const normalized: EditableLayoutSet = { lg: [], md: [], sm: [], xs: [] };

  for (const breakpoint of breakpoints) {
    const defaults = defaultLayouts[breakpoint] ?? [];
    const defaultMap = new Map(defaults.map((item) => [item.i, item]));
    const layoutItems: EditableLayoutItem[] = [];

    for (const block of blocks) {
      const fallback =
        block.defaultLayout?.[breakpoint] ??
        defaultMap.get(block.id) ?? {
        i: block.id,
        x: 0,
        y: layoutItems.length * 2,
        w: DEFAULT_COLUMNS[breakpoint],
        h: 8
      };
      const cols = DEFAULT_COLUMNS[breakpoint];
      const resolved = { ...fallback };
      if (fullWidthBlocks.includes(block.id)) {
        resolved.w = cols;
        resolved.x = 0;
      } else if (sidePanelBlocks.includes(block.id)) {
        const sideWidth = Math.min(4, cols);
        resolved.w = sideWidth;
        resolved.x = Math.max(0, cols - sideWidth);
      }
      layoutItems.push({
        ...resolved,
        i: block.id
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
    return defaults;
  }

  const blockMap = new Map(blocks.map((block) => [block.id, block]));
  const breakpoints: EditableLayoutBreakpoint[] = ["lg", "md", "sm", "xs"];
  const merged: EditableLayoutSet = { lg: [], md: [], sm: [], xs: [] };

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
      nextItems.push({
        ...savedItem,
        i: id
      });
    }

    for (const block of blocks) {
      if (nextItems.some((item) => item.i === block.id)) {
        continue;
      }
      const defaultItem = defaultMap.get(block.id) ?? {
        i: block.id,
        x: 0,
        y: nextItems.length * 2,
        w: DEFAULT_COLUMNS[breakpoint],
        h: 8
      };
      nextItems.push({
        ...defaultItem,
        i: block.id
      });
    }

    merged[breakpoint] = nextItems;
  }

  return sanitizeLayouts(merged, defaults);
}

function areLayoutsEqual(a: EditableLayoutSet, b: EditableLayoutSet): boolean {
  const breakpoints: EditableLayoutBreakpoint[] = ["lg", "md", "sm", "xs"];
  for (const breakpoint of breakpoints) {
    const sortItems = (items: EditableLayoutItem[]) =>
      [...items]
        .map((item) => ({
          i: item.i,
          x: item.x,
          y: item.y,
          w: item.w,
          h: item.h
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
        itemA.h !== itemB.h
      ) {
        return false;
      }
    }
  }
  return true;
}

function areHiddenBlocksEqual(a: string[], b: string[]): boolean {
  if (a.length !== b.length) {
    return false;
  }
  const sortedA = [...a].sort();
  const sortedB = [...b].sort();
  return sortedA.every((value, index) => value === sortedB[index]);
}

function mergeVisibleLayouts(
  previous: EditableLayoutSet,
  next: Partial<Record<EditableLayoutBreakpoint, EditableLayoutItem[]>>
): EditableLayoutSet {
  const breakpoints: EditableLayoutBreakpoint[] = ["lg", "md", "sm", "xs"];
  const merged: EditableLayoutSet = { lg: [], md: [], sm: [], xs: [] };

  for (const breakpoint of breakpoints) {
    const previousItems = previous[breakpoint] ?? [];
    const visibleItems = next[breakpoint] ?? previousItems;
    const nextItems = visibleItems.map((item) => ({ ...item }));

    const missingItems = previousItems.filter(
      (item) => !nextItems.some((visible) => visible.i === item.i)
    );

    merged[breakpoint] = [...nextItems, ...missingItems];
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
  pageKey,
  blocks,
  defaultLayouts,
  pagePermission,
  renderHeader,
  className,
  fullWidthBlocks = [],
  sidePanelBlocks = []
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
    () =>
      normalizeLayouts(defaultLayouts, allowedBlocks, fullWidthBlocks, sidePanelBlocks),
    [defaultLayouts, allowedBlocks, fullWidthBlocks, sidePanelBlocks]
  );

  const cachedLayout = useMemo(() => readLayoutCache(pageKey), [pageKey]);

  const layoutQuery = useQuery({
    queryKey: ["ui-layouts", pageKey],
    queryFn: async () => {
      try {
        const response = await api.get<{ layouts: EditableLayoutSet; hidden_blocks: string[] }>(
          `/user-layouts/${encodeURIComponent(pageKey)}`
        );
        return {
          layouts: response.data.layouts,
          hiddenBlocks: response.data.hidden_blocks ?? []
        };
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
    () =>
      mergeLayouts(
        fallbackLayouts,
        layoutQuery.data?.layouts ?? cachedLayout?.layouts ?? null,
        allowedBlocks
      ),
    [fallbackLayouts, layoutQuery.data?.layouts, cachedLayout?.layouts, allowedBlocks]
  );
  const mergedHiddenBlocks = useMemo(
    () =>
      mergeHiddenBlocks(
        allowedBlocks,
        layoutQuery.data?.hiddenBlocks ?? cachedLayout?.hiddenBlocks ?? null
      ),
    [allowedBlocks, layoutQuery.data?.hiddenBlocks, cachedLayout?.hiddenBlocks]
  );

  useEffect(() => {
    if (!layoutQuery.data) {
      return;
    }
    writeLayoutCache(pageKey, {
      layouts: layoutQuery.data.layouts,
      hiddenBlocks: layoutQuery.data.hiddenBlocks
    });
  }, [layoutQuery.data, pageKey]);

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
  const [activeHiddenBlocks, setActiveHiddenBlocks] = useState<string[]>(mergedHiddenBlocks);
  const [savedHiddenBlocks, setSavedHiddenBlocks] = useState<string[]>(mergedHiddenBlocks);
  const [isEditing, setIsEditing] = useState(false);

  useEffect(() => {
    if (!isEditing) {
      setActiveLayouts(mergedLayouts);
      setSavedLayouts(mergedLayouts);
      setActiveHiddenBlocks(mergedHiddenBlocks);
      setSavedHiddenBlocks(mergedHiddenBlocks);
    }
  }, [isEditing, mergedLayouts, mergedHiddenBlocks]);

  useEffect(() => {
    if (!canEditLayout && isEditing) {
      setIsEditing(false);
    }
  }, [canEditLayout, isEditing]);

  const isDirty = useMemo(
    () =>
      !areLayoutsEqual(activeLayouts, savedLayouts) ||
      !areHiddenBlocksEqual(activeHiddenBlocks, savedHiddenBlocks),
    [activeLayouts, savedLayouts, activeHiddenBlocks, savedHiddenBlocks]
  );

  useEffect(() => {
    if (!isEditing) {
      return;
    }
    writeLayoutCache(pageKey, {
      layouts: activeLayouts,
      hiddenBlocks: activeHiddenBlocks
    });
  }, [activeLayouts, activeHiddenBlocks, isEditing, pageKey]);

  const saveMutation = useMutation({
    mutationFn: async (payload: { layouts: EditableLayoutSet; hiddenBlocks: string[] }) => {
      const response = await api.put(`/user-layouts/${encodeURIComponent(pageKey)}`, {
        version: 1,
        page_key: pageKey,
        layouts: payload.layouts,
        hidden_blocks: payload.hiddenBlocks
      });
      return response.data;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["ui-layouts", pageKey] });
    }
  });

  const resetMutation = useMutation({
    mutationFn: async () => {
      await api.delete(`/user-layouts/${encodeURIComponent(pageKey)}`);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["ui-layouts", pageKey] });
    }
  });

  useEffect(() => {
    if (!isEditing || !isDirty) {
      return undefined;
    }
    const timeoutId = window.setTimeout(() => {
      saveMutation.mutate({
        layouts: activeLayouts,
        hiddenBlocks: activeHiddenBlocks
      });
      setSavedLayouts(activeLayouts);
      setSavedHiddenBlocks(activeHiddenBlocks);
    }, AUTO_SAVE_DELAY);
    return () => window.clearTimeout(timeoutId);
  }, [activeLayouts, activeHiddenBlocks, isDirty, isEditing, saveMutation]);

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
    setActiveHiddenBlocks((prev) => {
      if (requiredBlocks.has(blockId)) {
        return prev;
      }
      if (prev.includes(blockId)) {
        return prev.filter((id) => id !== blockId);
      }
      return [...prev, blockId];
    });
  }, [requiredBlocks]);

  const restoreBlock = useCallback((blockId: string) => {
    setActiveHiddenBlocks((prev) => prev.filter((id) => id !== blockId));
  }, []);

  const showEditButton = canEditLayout && (allowedBlocks.length > 1 || isAdmin);

  const editButton = showEditButton ? (
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
          if (isDirty) {
            await saveMutation.mutateAsync({
              layouts: activeLayouts,
              hiddenBlocks: activeHiddenBlocks
            });
            setSavedLayouts(activeLayouts);
            setSavedHiddenBlocks(activeHiddenBlocks);
          }
          writeLayoutCache(pageKey, {
            layouts: activeLayouts,
            hiddenBlocks: activeHiddenBlocks
          });
          setIsEditing(false);
        }}
        disabled={saveMutation.isPending}
        className="rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
      >
        {saveMutation.isPending ? "Enregistrement..." : "Enregistrer"}
      </button>
      <button
        type="button"
        onClick={() => {
          setActiveLayouts(savedLayouts);
          setActiveHiddenBlocks(savedHiddenBlocks);
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
          const defaultsHidden = mergeHiddenBlocks(allowedBlocks, null);
          setActiveHiddenBlocks(defaultsHidden);
          setSavedHiddenBlocks(defaultsHidden);
          writeLayoutCache(pageKey, {
            layouts: fallbackLayouts,
            hiddenBlocks: defaultsHidden
          });
        }}
        disabled={resetMutation.isPending}
        className="rounded-md border border-red-500/60 px-4 py-2 text-sm font-semibold text-red-200 hover:bg-red-500/10 disabled:cursor-not-allowed disabled:opacity-70"
      >
        Réinitialiser
      </button>
    </div>
  ) : null;

  const visibleLayouts = useMemo(() => {
    const filtered: EditableLayoutSet = { lg: [], md: [], sm: [], xs: [] };
    const hiddenSet = new Set(activeHiddenBlocks);
    (Object.keys(activeLayouts) as EditableLayoutBreakpoint[]).forEach((breakpoint) => {
      filtered[breakpoint] = activeLayouts[breakpoint].filter((item) => !hiddenSet.has(item.i));
    });
    return filtered;
  }, [activeLayouts, activeHiddenBlocks]);

  const hiddenBlocks = useMemo(() => {
    const hiddenIds = new Set(activeHiddenBlocks);
    return allowedBlocks.filter((block) => hiddenIds.has(block.id));
  }, [activeHiddenBlocks, allowedBlocks]);

  const sectionClassName = ["editable-page", "space-y-6", className]
    .filter(Boolean)
    .join(" ");
  const constrainedLayouts = useMemo(
    () => applyBlockConstraints(visibleLayouts, allowedBlocks),
    [visibleLayouts, allowedBlocks]
  );

  return (
    <section className={sectionClassName}>
      {renderHeader ? renderHeader({ isEditing, isDirty, editButton, actionButtons }) : null}
      <ResponsiveGridLayout
        className="layout"
        layouts={constrainedLayouts}
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
          .filter((block) => !activeHiddenBlocks.includes(block.id))
          .map((block) => {
            const baseClassName =
              block.containerClassName ?? "rounded-lg border border-slate-800 bg-slate-900 p-4";
            const editingClassName = isEditing ? "ring-1 ring-slate-700" : "";
            const containerClassName = [
              "min-w-0 max-w-full min-h-0 h-full",
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
                        activeHiddenBlocks.includes(block.id)
                          ? "Afficher ce bloc"
                          : "Masquer ce bloc"
                      }
                    >
                      <EyeIcon
                        hidden={activeHiddenBlocks.includes(block.id)}
                      />
                      {activeHiddenBlocks.includes(block.id) ? "Afficher" : "Masquer"}
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
