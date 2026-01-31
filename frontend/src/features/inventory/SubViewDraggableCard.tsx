import clsx from "clsx";
import { CSS } from "@dnd-kit/utilities";
import { useDraggable } from "@dnd-kit/core";
import { KeyboardEvent, MouseEvent } from "react";

export type SubviewCardData = {
  id: string;
  label: string;
  itemCount?: number;
  isPinned?: boolean;
};

type SubviewDragData = {
  kind: "SUBVIEW_CARD";
  subviewId: string;
  parentViewId: string;
  vehicleId: number;
};

interface SubViewDraggableCardProps {
  subview: SubviewCardData;
  onOpen: (subviewId: string) => void;
  dragData?: SubviewDragData;
  draggable?: boolean;
}

export function SubViewDraggableCard({
  subview,
  onOpen,
  dragData,
  draggable = false
}: SubViewDraggableCardProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    isDragging
  } = useDraggable({
    id: `subview-card-${subview.id}`,
    data: dragData,
    disabled: !draggable
  });
  const style = transform ? { transform: CSS.Translate.toString(transform) } : undefined;
  const itemCountLabel =
    typeof subview.itemCount === "number"
      ? `${subview.itemCount} équipement${subview.itemCount > 1 ? "s" : ""}`
      : null;

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onOpen(subview.id);
    }
  };

  const handleHandleClick = (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
  };

  return (
    <div
      ref={setNodeRef}
      role="button"
      tabIndex={0}
      onClick={() => onOpen(subview.id)}
      onKeyDown={handleKeyDown}
      style={style}
      className={clsx(
        "group flex min-w-0 flex-col gap-3 rounded-xl border border-slate-200 bg-white p-3 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-md focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-slate-700 dark:bg-slate-900 dark:hover:border-slate-600",
        subview.isPinned &&
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
        {draggable ? (
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
          <span className="text-lg" aria-hidden>
            📌
          </span>
        )}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-600 dark:bg-slate-800 dark:text-slate-200">
          {subview.isPinned ? "Épinglée" : "Sous-vue"}
        </span>
        <span className="rounded-md border border-slate-200 px-2 py-1 text-[11px] font-semibold text-slate-600 transition group-hover:border-slate-300 group-hover:text-slate-800 dark:border-slate-600 dark:text-slate-300 dark:group-hover:border-slate-500 dark:group-hover:text-white">
          Ouvrir
        </span>
      </div>
    </div>
  );
}
