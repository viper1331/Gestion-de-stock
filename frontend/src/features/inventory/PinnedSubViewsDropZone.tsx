import clsx from "clsx";
import { useDroppable } from "@dnd-kit/core";

import { SubViewCard, SubviewCardData } from "./SubViewCard";

interface PinnedSubViewsDropZoneProps {
  parentViewId: string;
  pinnedSubviews: SubviewCardData[];
  onOpenSubview?: (subviewId: string) => void;
  onRemovePinnedSubview?: (subviewId: string) => void;
}

export function PinnedSubViewsDropZone({
  parentViewId,
  pinnedSubviews,
  onOpenSubview,
  onRemovePinnedSubview
}: PinnedSubViewsDropZoneProps) {
  const { isOver, setNodeRef, active } = useDroppable({
    id: `PINNED_SUBVIEWS:${parentViewId}`,
    data: { accepts: ["SUBVIEW"] }
  });
  const isSubviewDragging = active?.data.current?.kind === "SUBVIEW";

  return (
    <div className="space-y-3">
      <div>
        <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
          Sous-vues épinglées sur cette vue
        </p>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Déposez ici une sous-vue pour l'afficher dans la vue principale.
        </p>
      </div>
      <div
        ref={setNodeRef}
        className={clsx(
          "grid gap-3 rounded-2xl border border-dashed border-slate-200 bg-white/80 p-4 transition dark:border-slate-700 dark:bg-slate-900/50 sm:grid-cols-2 xl:grid-cols-3",
          isOver && isSubviewDragging
            ? "border-blue-400 bg-blue-50/60 dark:border-blue-500 dark:bg-blue-950/40"
            : "border-slate-200"
        )}
      >
        {pinnedSubviews.length === 0 ? (
          <div className="col-span-full rounded-lg border border-dashed border-slate-300 bg-white p-4 text-center text-xs text-slate-500 shadow-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
            Déposez ici une sous-vue…
          </div>
        ) : null}
        {pinnedSubviews.map((subview) => (
          <SubViewCard
            key={subview.id}
            subview={subview}
            mode="pinned"
            onOpen={onOpenSubview}
            onRemove={onRemovePinnedSubview}
          />
        ))}
      </div>
    </div>
  );
}
