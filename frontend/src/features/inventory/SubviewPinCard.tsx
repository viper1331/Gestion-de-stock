import clsx from "clsx";
import { CSS } from "@dnd-kit/utilities";
import { useDraggable } from "@dnd-kit/core";
import { KeyboardEvent, MouseEvent } from "react";

export type SubviewPinCardData = {
  id: number;
  subviewId: string;
  label: string;
  itemCount?: number;
  xPct: number;
  yPct: number;
};

interface SubviewPinCardProps {
  pin: SubviewPinCardData;
  onOpen?: (subviewId: string) => void;
  onRemove?: (pinId: number) => void;
}

export function SubviewPinCard({ pin, onOpen, onRemove }: SubviewPinCardProps) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: `subview-pin:${pin.id}`,
    data: {
      kind: "SUBVIEW_PIN",
      pinId: pin.id,
      subviewId: pin.subviewId,
      xPct: pin.xPct,
      yPct: pin.yPct
    }
  });
  const dragTransform = transform ? CSS.Translate.toString(transform) : "";
  const resolvedTransform = dragTransform
    ? `${dragTransform} translate(-50%, -100%)`
    : "translate(-50%, -100%)";
  const itemCountLabel =
    typeof pin.itemCount === "number"
      ? `${pin.itemCount} équipement${pin.itemCount > 1 ? "s" : ""}`
      : null;

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!onOpen || isDragging) {
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onOpen(pin.subviewId);
    }
  };

  const handleRemove = (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    onRemove?.(pin.id);
  };

  const handleOpen = (event: MouseEvent<HTMLDivElement>) => {
    if (!onOpen || isDragging) {
      return;
    }
    event.stopPropagation();
    onOpen(pin.subviewId);
  };

  return (
    <div
      ref={setNodeRef}
      role={onOpen ? "button" : undefined}
      tabIndex={onOpen ? 0 : -1}
      onClick={handleOpen}
      onKeyDown={handleKeyDown}
      style={{
        left: `${pin.xPct * 100}%`,
        top: `${pin.yPct * 100}%`,
        transform: resolvedTransform
      }}
      className={clsx(
        "absolute z-20 flex max-w-[220px] cursor-grab flex-col gap-2 rounded-lg border border-slate-200 bg-white/90 px-3 py-2 text-left text-xs text-slate-700 shadow-md backdrop-blur-md transition hover:border-indigo-300 hover:text-slate-900 dark:border-slate-600 dark:bg-slate-900/90 dark:text-slate-200 dark:hover:border-indigo-400",
        isDragging && "cursor-grabbing opacity-80"
      )}
      {...attributes}
      {...listeners}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-[13px] font-semibold">{pin.label}</p>
          {itemCountLabel ? (
            <p className="text-[11px] text-slate-500 dark:text-slate-400">{itemCountLabel}</p>
          ) : null}
        </div>
        {onRemove ? (
          <button
            type="button"
            onClick={handleRemove}
            className="rounded-md border border-rose-200 px-2 py-1 text-[10px] font-semibold text-rose-600 transition hover:border-rose-300 hover:text-rose-700 dark:border-rose-500/40 dark:text-rose-200 dark:hover:border-rose-400"
          >
            Retirer
          </button>
        ) : null}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-indigo-700 dark:bg-indigo-900/60 dark:text-indigo-200">
          Sous-vue
        </span>
        <span className="text-[10px] font-semibold uppercase text-slate-500 dark:text-slate-400">
          Cliquer pour ouvrir
        </span>
      </div>
    </div>
  );
}
