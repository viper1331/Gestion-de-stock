import { useCallback, useEffect, useLayoutEffect, useRef, useState, type MouseEvent } from "react";
import { createPortal } from "react-dom";
import { AppTextInput } from "components/AppTextInput";

interface ColumnOption {
  key: string;
  label: string;
  kind?: "native" | "custom";
}

interface ColumnManagerProps {
  options: ColumnOption[];
  visibility: Record<string, boolean>;
  onToggle: (key: string) => void;
  onReset?: () => void;
  title?: string;
  description?: string;
  minVisibleColumns?: number;
}

export function ColumnManager({
  options,
  visibility,
  onToggle,
  onReset,
  title = "Colonnes",
  description,
  minVisibleColumns = 1
}: ColumnManagerProps) {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [menuPosition, setMenuPosition] = useState({ top: 0, left: 0 });
  const menuWidth = 224;

  const updateMenuPosition = useCallback(() => {
    const trigger = containerRef.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const measuredWidth = menuRef.current?.offsetWidth ?? menuWidth;
    const measuredHeight = menuRef.current?.offsetHeight ?? 0;
    const left = Math.min(
      window.innerWidth - measuredWidth - 8,
      Math.max(8, rect.right - measuredWidth)
    );
    const top = Math.min(
      window.innerHeight - measuredHeight - 8,
      Math.max(8, rect.bottom + 8)
    );
    setMenuPosition({ top, left });
  }, [menuWidth]);

  useEffect(() => {
    if (!isOpen) return;

    const handleClickOutside = (event: PointerEvent) => {
      const container = containerRef.current;
      const menu = menuRef.current;
      if (!container || !menu) return;
      const target = event.target as Node;
      if (!container.contains(target) && !menu.contains(target)) {
        setIsOpen(false);
      }
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsOpen(false);
      }
    };

    document.addEventListener("pointerdown", handleClickOutside);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handleClickOutside);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  useLayoutEffect(() => {
    if (!isOpen) return;
    updateMenuPosition();

    const handleReposition = () => {
      updateMenuPosition();
    };

    window.addEventListener("resize", handleReposition);
    window.addEventListener("scroll", handleReposition, true);
    return () => {
      window.removeEventListener("resize", handleReposition);
      window.removeEventListener("scroll", handleReposition, true);
    };
  }, [isOpen, updateMenuPosition]);

  const handleToggle = (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    setIsOpen((value) => !value);
  };

  const isOptionVisible = (option: ColumnOption) => {
    if (visibility[option.key] !== undefined) {
      return visibility[option.key] !== false;
    }
    return option.kind === "custom" ? false : true;
  };

  const visibleCount = options.reduce(
    (count, option) => (isOptionVisible(option) ? count + 1 : count),
    0
  );
  const hasCustomOptions = options.some((option) => option.kind === "custom");
  const hasNativeOptions = options.some((option) => option.kind !== "custom");
  const groupedOptions = hasCustomOptions && hasNativeOptions
    ? [
        {
          label: "Colonnes natives",
          items: options.filter((option) => option.kind !== "custom")
        },
        {
          label: "Colonnes personnalisées",
          items: options.filter((option) => option.kind === "custom")
        }
      ]
    : [{ label: null, items: options }];

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={handleToggle}
        className="rounded-md border border-slate-700 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-200 hover:bg-slate-800"
        title="Sélectionner les colonnes à afficher"
      >
        {title}
      </button>
      {isOpen
        ? createPortal(
            <div
              ref={menuRef}
              className="fixed z-50 w-56 rounded-md border border-slate-800 bg-slate-950 p-3 shadow-xl"
              style={{ top: menuPosition.top, left: menuPosition.left }}
            >
              <div className="space-y-2">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-300">{title}</p>
                  {description ? (
                    <p className="mt-1 text-[11px] leading-snug text-slate-400">{description}</p>
                  ) : null}
                </div>
                <div className="space-y-2 text-sm text-slate-200">
                  {groupedOptions.map((group) => (
                    <div key={group.label ?? "columns"} className="space-y-1">
                      {group.label ? (
                        <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                          {group.label}
                        </p>
                      ) : null}
                      <ul className="space-y-1">
                        {group.items.map((option) => {
                          const checked = isOptionVisible(option);
                          const disableCheckbox = checked && visibleCount <= minVisibleColumns;
                          return (
                            <li key={option.key} className="flex items-center justify-between gap-2">
                              <label className="flex items-center gap-2">
                                <AppTextInput
                                  type="checkbox"
                                  checked={checked}
                                  onChange={() => onToggle(option.key)}
                                  disabled={disableCheckbox}
                                  className="h-4 w-4 rounded border-slate-700 bg-slate-900 text-indigo-500 focus:ring-indigo-500"
                                />
                                <span className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-slate-300">
                                  {option.label}
                                  {option.kind === "custom" ? (
                                    <span className="rounded border border-indigo-500/40 bg-indigo-500/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-indigo-200">
                                      Personnalisé
                                    </span>
                                  ) : null}
                                </span>
                              </label>
                            </li>
                          );
                        })}
                      </ul>
                    </div>
                  ))}
                </div>
                {onReset ? (
                  <button
                    type="button"
                    onClick={() => {
                      onReset();
                      setIsOpen(false);
                    }}
                    className="w-full rounded-md border border-slate-700 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-300 hover:bg-slate-900"
                    title="Réinitialiser les colonnes à leur configuration par défaut"
                  >
                    Réinitialiser
                  </button>
                ) : null}
              </div>
            </div>,
            document.body
          )
        : null}
    </div>
  );
}
