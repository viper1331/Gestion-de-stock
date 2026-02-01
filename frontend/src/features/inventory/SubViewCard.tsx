import clsx from "clsx";
import { CSS } from "@dnd-kit/utilities";
import { useDraggable } from "@dnd-kit/core";
import { KeyboardEvent, MouseEvent } from "react";

export type SubviewCardData = {
  id: string;
  label: string;
  itemCount?: number;
};

type SubviewDragData = {
  kind: "SUBVIEW";
  subviewId: string;
  parentViewId: string;
  vehicleId: number;
};

interface SubViewCardProps {
  subview: SubviewCardData;
  mode: "draggable" | "pinned";
  dragData?: SubviewDragData;
  onOpen?: (subviewId: string) => void;
  onRemove?: (subviewId: string) => void;
}

interface CompactSubViewTileProps {
  subview: SubviewCardData;
  dragData: SubviewDragData;
}

export function SubViewCard({
  subview,
  mode,
  dragData,
  onOpen,
  onRemove
}: SubViewCardProps) {
  const isDraggable = mode === "draggable";
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    isDragging
  } = useDraggable({
    id: `subview:${subview.id}`,
    data: dragData,
    disabled: !isDraggable
  });
  const style = transform ? { transform: CSS.Translate.toString(transform) } : undefined;
  const itemCountLabel =
    typeof subview.itemCount === "number"
      ? `${subview.itemCount} équipement${subview.itemCount > 1 ? "s" : ""}`
      : null;

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!onOpen) {
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onOpen(subview.id);
    }
  };

  const handleHandleClick = (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
  };

  const handleRemove = (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    onRemove?.(subview.id);
  };

  return (
    <div
      ref={setNodeRef}
      role={onOpen ? "button" : undefined}
      tabIndex={onOpen ? 0 : -1}
      onClick={onOpen ? () => onOpen(subview.id) : undefined}
      onKeyDown={handleKeyDown}
      style={style}
      className={clsx(
        "group flex min-w-0 flex-col gap-3 rounded-xl border border-slate-200 bg-white p-3 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-md focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-slate-700 dark:bg-slate-900 dark:hover:border-slate-600",
        mode === "pinned" &&
          "border-indigo-200 bg-indigo-50/40 dark:border-indigo-500/40 dark:bg-indigo-950/40",
        isDragging && "opacity-70"
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            {subview.label}
          </p>
          {itemCountLabel ? (
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{itemCountLabel}</p>
          ) : null}
        </div>
        {isDraggable ? (
          <button
            type="button"
            ref={setActivatorNodeRef}
            onClick={handleHandleClick}
            className="flex h-8 w-8 items-center justify-center rounded-md border border-slate-200 text-slate-400 transition hover:border-slate-300 hover:text-slate-600 dark:border-slate-600 dark:text-slate-300 dark:hover:border-slate-500 dark:hover:text-white"
            {...listeners}
            {...attributes}
          >
            <span className="sr-only">Glisser</span>
            <span aria-hidden>⠿</span>
          </button>
        ) : (
          <button
            type="button"
            onClick={handleRemove}
            className="rounded-md border border-rose-200 px-2 py-1 text-[11px] font-semibold text-rose-600 transition hover:border-rose-300 hover:text-rose-700 dark:border-rose-500/40 dark:text-rose-200 dark:hover:border-rose-400"
          >
            Retirer
          </button>
        )}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-600 dark:bg-slate-800 dark:text-slate-200">
          {mode === "pinned" ? "Épinglée" : "Sous-vue"}
        </span>
        {onOpen ? (
          <span className="rounded-md border border-slate-200 px-2 py-1 text-[11px] font-semibold text-slate-600 transition group-hover:border-slate-300 group-hover:text-slate-800 dark:border-slate-600 dark:text-slate-300 dark:group-hover:border-slate-500 dark:group-hover:text-white">
            Ouvrir
          </span>
        ) : null}
      </div>
    </div>
  );
}

export function CompactSubViewTile({ subview, dragData }: CompactSubViewTileProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    isDragging
  } = useDraggable({
    id: `subview:${subview.id}`,
    data: dragData
  });
  const style = transform ? { transform: CSS.Translate.toString(transform) } : undefined;
  const itemCountLabel =
    typeof subview.itemCount === "number"
      ? `${subview.itemCount} équipement${subview.itemCount > 1 ? "s" : ""}`
      : null;

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={clsx(
        "flex min-w-0 items-center justify-between gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-left transition hover:bg-white/8",
        isDragging && "opacity-70"
      )}
      {...attributes}
      {...listeners}
    >
      <div className="min-w-0">
        <p
          className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100"
          title={subview.label}
        >
          {subview.label}
        </p>
        {itemCountLabel ? (
          <p className="text-xs text-slate-500 dark:text-slate-400">{itemCountLabel}</p>
        ) : null}
      </div>
      <button
        type="button"
        ref={setActivatorNodeRef}
        className="flex h-8 w-8 items-center justify-center rounded-md border border-white/10 text-slate-400 transition hover:border-white/20 hover:text-slate-600 dark:text-slate-300 dark:hover:text-white"
      >
        <span className="sr-only">Glisser</span>
        <span aria-hidden>⠿</span>
      </button>
    </div>
  );
}
