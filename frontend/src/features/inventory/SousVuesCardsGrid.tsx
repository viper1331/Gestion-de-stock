import clsx from "clsx";
import { DragEvent, KeyboardEvent } from "react";

export type SubviewCardData = {
  id: string;
  label: string;
  itemCount?: number;
  isPinned?: boolean;
};

interface SousVuesCardsGridProps {
  title?: string;
  subtitle?: string;
  subviews: SubviewCardData[];
  onOpen: (subviewId: string) => void;
  onPin?: (subviewId: string) => void;
  onDragStart?: (event: DragEvent<HTMLElement>, subviewId: string) => void;
  showPinAction?: boolean;
}

interface SubViewCardDraggableProps {
  subview: SubviewCardData;
  onOpen: (subviewId: string) => void;
  onPin?: (subviewId: string) => void;
  onDragStart?: (event: DragEvent<HTMLElement>, subviewId: string) => void;
  showPinAction?: boolean;
}

export function SubViewCardDraggable({
  subview,
  onOpen,
  onPin,
  onDragStart,
  showPinAction = false
}: SubViewCardDraggableProps) {
  const itemCountLabel =
    typeof subview.itemCount === "number"
      ? `${subview.itemCount} équipement${subview.itemCount > 1 ? "s" : ""}`
      : null;
  const badgeLabel = subview.isPinned ? "Épinglée" : "Sous-vue";

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onOpen(subview.id);
    }
  };

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onOpen(subview.id)}
      onKeyDown={handleKeyDown}
      draggable={Boolean(onDragStart)}
      onDragStart={(event) => onDragStart?.(event, subview.id)}
      className={clsx(
        "group flex min-w-0 flex-col gap-3 rounded-xl border border-slate-200 bg-white p-3 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-md focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-slate-700 dark:bg-slate-900 dark:hover:border-slate-600",
        Boolean(onDragStart) ? "cursor-move" : "cursor-pointer",
        subview.isPinned && "border-indigo-200 bg-indigo-50/40 dark:border-indigo-500/40 dark:bg-indigo-950/40"
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            {subview.label}
          </p>
          {itemCountLabel ? (
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              {itemCountLabel}
            </p>
          ) : null}
        </div>
        <span className="text-lg" aria-hidden>
          🧭
        </span>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-600 dark:bg-slate-800 dark:text-slate-200">
          {badgeLabel}
        </span>
        <div className="flex items-center gap-2">
          <span className="rounded-md border border-slate-200 px-2 py-1 text-[11px] font-semibold text-slate-600 transition group-hover:border-slate-300 group-hover:text-slate-800 dark:border-slate-600 dark:text-slate-300 dark:group-hover:border-slate-500 dark:group-hover:text-white">
            Ouvrir
          </span>
          {showPinAction && onPin ? (
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                onPin(subview.id);
              }}
              className="rounded-md border border-indigo-200 px-2 py-1 text-[11px] font-semibold text-indigo-600 transition hover:border-indigo-300 hover:text-indigo-700 dark:border-indigo-500/40 dark:text-indigo-200 dark:hover:border-indigo-400"
            >
              Épingler
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function SousVuesCardsGrid({
  title,
  subtitle,
  subviews,
  onOpen,
  onPin,
  onDragStart,
  showPinAction = false
}: SousVuesCardsGridProps) {
  return (
    <section className="space-y-3">
      {title ? (
        <div>
          <p className="text-sm font-semibold uppercase tracking-wide text-slate-600 dark:text-slate-200">
            {title}
          </p>
          {subtitle ? (
            <p className="text-xs text-slate-500 dark:text-slate-400">{subtitle}</p>
          ) : null}
        </div>
      ) : null}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {subviews.map((subview) => (
          <SubViewCardDraggable
            key={subview.id}
            subview={subview}
            onOpen={onOpen}
            onPin={onPin}
            onDragStart={onDragStart}
            showPinAction={showPinAction}
          />
        ))}
      </div>
    </section>
  );
}
