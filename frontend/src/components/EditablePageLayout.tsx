import { ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import {
  DndContext,
  DragOverlay,
  type DragEndEvent,
  type DragStartEvent,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { isAxiosError } from "axios";

import { api } from "../lib/api";
import { useAuth } from "../features/auth/useAuth";
import { useModulePermissions } from "../features/permissions/useModulePermissions";
import { PageBlockCard } from "./PageBlockCard";
import { SafeBlock } from "./SafeBlock";

export type EditableLayoutBreakpoint = "lg" | "md" | "sm" | "xs";

export type EditableLayoutItem = {
  i: string;
  x: number;
  y: number;
  w: number;
  h: number;
  minH?: number;
  maxH?: number;
  isResizable?: boolean;
};

export type EditableLayoutSet = Record<EditableLayoutBreakpoint, EditableLayoutItem[]>;

export type EditablePageBlock = {
  id: string;
  title?: string;
  render: () => ReactNode;
  defaultLayout: Partial<Record<EditableLayoutBreakpoint, Omit<EditableLayoutItem, "i">>>;
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
const MIN_LAYOUT_SIZE = 1;

const BREAKPOINTS: EditableLayoutBreakpoint[] = ["lg", "md", "sm", "xs"];

function clampLayoutItem(item: EditableLayoutItem, cols: number): EditableLayoutItem {
  const w = Math.min(cols, Math.max(MIN_LAYOUT_SIZE, Math.floor(item.w ?? cols)));
  const h = Math.max(MIN_LAYOUT_SIZE, Math.floor(item.h ?? MIN_LAYOUT_SIZE));
  let x = Math.max(0, Math.floor(item.x ?? 0));
  let y = Math.max(0, Math.floor(item.y ?? 0));

  if (x + w > cols) {
    x = Math.max(0, cols - w);
  }

  return { ...item, x, y, w, h };
}

function layoutsOverlap(first: EditableLayoutItem, second: EditableLayoutItem): boolean {
  return (
    first.x < second.x + second.w &&
    first.x + first.w > second.x &&
    first.y < second.y + second.h &&
    first.y + first.h > second.y
  );
}

function normalizeLayoutItems(
  items: EditableLayoutItem[],
  cols: number,
  blocksById: Map<string, EditablePageBlock>
): EditableLayoutItem[] {
  const seen = new Set<string>();
  const normalized: EditableLayoutItem[] = [];

  for (const rawItem of items) {
    const id = rawItem.i;
    const block = blocksById.get(id);
    if (!block || seen.has(id)) {
      continue;
    }
    seen.add(id);

    const clamped = clampLayoutItem(rawItem, cols);
    const candidate: EditableLayoutItem = {
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
      const fallback = {
        x: 0,
        y: nextY,
        w: cols,
        h: 8
      };
      const base = block.defaultLayout[breakpoint] ?? fallback;
      const clamped = clampLayoutItem({ ...base, i: block.id }, cols);
      const item: EditableLayoutItem = {
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
      const mergedItem: EditableLayoutItem = {
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

function areSetsEqual(a: Set<string>, b: Set<string>) {
  if (a.size !== b.size) {
    return false;
  }
  for (const entry of a) {
    if (!b.has(entry)) {
      return false;
    }
  }
  return true;
}

export function mergeOrder(defaultOrder: string[], savedOrder: string[] | null): string[] {
  if (!savedOrder || savedOrder.length === 0) {
    return [...defaultOrder];
  }
  const defaultSet = new Set(defaultOrder);
  const merged = savedOrder.filter((entry) => defaultSet.has(entry));
  for (const entry of defaultOrder) {
    if (!merged.includes(entry)) {
      merged.push(entry);
    }
  }
  return merged;
}

export function extractOrderFromLayouts(layouts: EditableLayoutSet | null): string[] | null {
  if (!layouts) {
    return null;
  }
  for (const breakpoint of BREAKPOINTS) {
    const items = layouts[breakpoint] ?? [];
    if (items.length === 0) {
      continue;
    }
    return [...items]
      .sort((first, second) => {
        if (first.y !== second.y) {
          return first.y - second.y;
        }
        if (first.x !== second.x) {
          return first.x - second.x;
        }
        return first.i.localeCompare(second.i);
      })
      .map((item) => item.i);
  }
  return null;
}

export function applyVisibleOrder(
  fullOrder: string[],
  visibleOrder: string[],
  hiddenBlocks: Set<string>
): string[] {
  let visibleIndex = 0;
  return fullOrder.map((entry) => {
    if (hiddenBlocks.has(entry)) {
      return entry;
    }
    const next = visibleOrder[visibleIndex];
    visibleIndex += 1;
    return next ?? entry;
  });
}

function areOrdersEqual(a: string[], b: string[]): boolean {
  if (a.length !== b.length) {
    return false;
  }
  for (let index = 0; index < a.length; index += 1) {
    if (a[index] !== b[index]) {
      return false;
    }
  }
  return true;
}

function buildLayoutsFromOrder(order: string[], blocks: EditablePageBlock[]): EditableLayoutSet {
  const blocksById = new Map(blocks.map((block) => [block.id, block]));
  const layoutSet: EditableLayoutSet = { lg: [], md: [], sm: [], xs: [] };

  for (const breakpoint of BREAKPOINTS) {
    const cols = LAYOUT_COLUMNS[breakpoint];
    let nextY = 0;

    for (const id of order) {
      const block = blocksById.get(id);
      if (!block) {
        continue;
      }
      const fallback = {
        x: 0,
        y: nextY,
        w: cols,
        h: 8
      };
      const base = block.defaultLayout[breakpoint] ?? fallback;
      const clamped = clampLayoutItem({ ...base, i: id }, cols);
      const item: EditableLayoutItem = {
        ...clamped,
        x: 0,
        y: nextY,
        w: cols,
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

function SortableBlockCard({
  block,
  isEditing,
  isHidden,
  onToggleHidden
}: {
  block: EditablePageBlock;
  isEditing: boolean;
  isHidden: boolean;
  onToggleHidden: (blockId: string) => void;
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    transition,
    isDragging
  } = useSortable({ id: block.id, disabled: !isEditing });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition
  };

  const header = isEditing ? (
    <div className="flex items-center justify-between gap-3">
      <div className="flex items-center gap-2">
        <button
          type="button"
          ref={setActivatorNodeRef}
          className="layout-drag-handle relative z-10 inline-flex h-7 w-7 cursor-grab items-center justify-center rounded border border-slate-700 text-slate-300 hover:text-white active:cursor-grabbing"
          title="Déplacer le bloc"
          aria-label={`Déplacer ${block.title ?? block.id}`}
          {...attributes}
          {...listeners}
        >
          <span className="select-none text-xs">↕</span>
        </button>
        <h3 className="text-sm font-semibold text-white">{block.title ?? block.id}</h3>
      </div>
      <button
        type="button"
        onClick={() => onToggleHidden(block.id)}
        disabled={block.required}
        className="inline-flex items-center gap-2 text-xs font-semibold text-slate-200 hover:text-white"
        title={isHidden ? "Afficher ce bloc" : "Masquer ce bloc"}
      >
        <EyeIcon hidden={isHidden} />
        {isHidden ? "Afficher" : "Masquer"}
      </button>
    </div>
  ) : undefined;

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={clsx("relative", isDragging && "z-20 opacity-40")}
    >
      <PageBlockCard
        title={block.title}
        actions={block.headerActions}
        header={header}
        variant={block.variant ?? "card"}
        bodyClassName={block.bodyClassName}
      >
        <SafeBlock>{block.render()}</SafeBlock>
      </PageBlockCard>
    </div>
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

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

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

  const defaultOrder = useMemo(() => allowedBlocks.map((block) => block.id), [allowedBlocks]);
  const savedOrder = useMemo(
    () => mergeOrder(defaultOrder, extractOrderFromLayouts(mergedLayouts)),
    [defaultOrder, mergedLayouts]
  );

  const [order, setOrder] = useState<string[]>(savedOrder);
  const [savedOrderState, setSavedOrderState] = useState<string[]>(savedOrder);
  const [draftOrder, setDraftOrder] = useState<string[] | null>(null);
  const [hiddenBlocks, setHiddenBlocks] = useState<Set<string>>(mergedHiddenBlocks);
  const [savedHiddenBlocks, setSavedHiddenBlocks] = useState<Set<string>>(mergedHiddenBlocks);
  const [isEditing, setIsEditing] = useState(false);
  const [activeId, setActiveId] = useState<string | null>(null);

  useEffect(() => {
    if (!isEditing) {
      setOrder((prev) => (areOrdersEqual(prev, savedOrder) ? prev : savedOrder));
      setSavedOrderState((prev) => (areOrdersEqual(prev, savedOrder) ? prev : savedOrder));
      setHiddenBlocks((prev) =>
        areSetsEqual(prev, mergedHiddenBlocks) ? prev : new Set(mergedHiddenBlocks)
      );
      setSavedHiddenBlocks((prev) =>
        areSetsEqual(prev, mergedHiddenBlocks) ? prev : new Set(mergedHiddenBlocks)
      );
    }
  }, [isEditing, mergedHiddenBlocks, savedOrder]);

  const isLayoutLoading = layoutQuery.isLoading && !layoutQuery.data;

  const effectiveOrder = isEditing ? (draftOrder ?? order) : order;

  const isDirty = useMemo(() => {
    if (!areOrdersEqual(effectiveOrder, savedOrderState)) {
      return true;
    }
    return !areSetsEqual(hiddenBlocks, savedHiddenBlocks);
  }, [effectiveOrder, hiddenBlocks, savedHiddenBlocks, savedOrderState]);

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
      onClick={() => {
        setIsEditing(true);
        setDraftOrder(null);
      }}
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
          const nextOrder = draftOrder ?? order;
          const layout = buildLayoutsFromOrder(nextOrder, allowedBlocks);
          const hiddenIds = Array.from(hiddenBlocks);
          await saveMutation.mutateAsync({ layout, hiddenBlocks: hiddenIds });
          setOrder(nextOrder);
          setSavedOrderState(nextOrder);
          setSavedHiddenBlocks(new Set(hiddenBlocks));
          setDraftOrder(null);
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
          setOrder(savedOrderState);
          setHiddenBlocks(new Set(savedHiddenBlocks));
          setDraftOrder(null);
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
          setDraftOrder(defaultOrder);
          setHiddenBlocks(new Set());
        }}
        className="rounded-md border border-red-500/60 px-4 py-2 text-sm font-semibold text-red-200 hover:bg-red-500/10"
      >
        Réinitialiser
      </button>
    </div>
  ) : null;

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

  const visibleOrder = useMemo(
    () => effectiveOrder.filter((blockId) => !hiddenBlocks.has(blockId)),
    [effectiveOrder, hiddenBlocks]
  );

  const blocksById = useMemo(
    () => new Map(allowedBlocks.map((block) => [block.id, block])),
    [allowedBlocks]
  );

  const orderedBlocks = useMemo(
    () => visibleOrder.map((id) => blocksById.get(id)).filter(Boolean) as EditablePageBlock[],
    [blocksById, visibleOrder]
  );

  const hiddenBlockList = useMemo(
    () => allowedBlocks.filter((block) => hiddenBlocks.has(block.id)),
    [allowedBlocks, hiddenBlocks]
  );

  const handleDragStart = useCallback(
    (event: DragStartEvent) => {
      if (!isEditing) {
        return;
      }
      setActiveId(String(event.active.id));
    },
    [isEditing]
  );

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      setActiveId(null);
      if (!isEditing) {
        return;
      }
      const { active, over } = event;
      if (!over || active.id === over.id) {
        return;
      }
      const activeKey = String(active.id);
      const overKey = String(over.id);
      setDraftOrder((prev) => {
        const current = prev ?? order;
        const visible = current.filter((blockId) => !hiddenBlocks.has(blockId));
        const oldIndex = visible.indexOf(activeKey);
        const newIndex = visible.indexOf(overKey);
        if (oldIndex === -1 || newIndex === -1) {
          return current;
        }
        const nextVisible = arrayMove(visible, oldIndex, newIndex);
        return applyVisibleOrder(current, nextVisible, hiddenBlocks);
      });
    },
    [hiddenBlocks, isEditing, order]
  );

  const activeBlock = activeId ? blocksById.get(activeId) ?? null : null;

  const sectionClassName = [
    "editable-page",
    "relative",
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
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
        autoScroll
      >
        <SortableContext items={visibleOrder} strategy={verticalListSortingStrategy}>
          <div className="space-y-6">
            {orderedBlocks.map((block) => (
              <SortableBlockCard
                key={block.id}
                block={block}
                isEditing={isEditing}
                isHidden={hiddenBlocks.has(block.id)}
                onToggleHidden={toggleHidden}
              />
            ))}
          </div>
        </SortableContext>
        <DragOverlay>
          {activeBlock ? (
            <div className="pointer-events-none">
              <PageBlockCard
                title={activeBlock.title}
                actions={activeBlock.headerActions}
                variant={activeBlock.variant ?? "card"}
                bodyClassName={activeBlock.bodyClassName}
                className="shadow-2xl"
              >
                <SafeBlock>{activeBlock.render()}</SafeBlock>
              </PageBlockCard>
            </div>
          ) : null}
        </DragOverlay>
      </DndContext>
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
