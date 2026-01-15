import { useCallback, useEffect, useLayoutEffect, useRef, useState, type MouseEvent } from "react";
import { createPortal } from "react-dom";
import { AppTextInput } from "components/AppTextInput";

interface ColumnOption {
  key: string;
  label: string;
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

  const visibleCount = options.reduce(
    (count, option) => (visibility[option.key] !== false ? count + 1 : count),
    0
  );

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
                <ul className="space-y-1 text-sm text-slate-200">
                  {options.map((option) => {
                    const checked = visibility[option.key] !== false;
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
                          <span className="text-xs font-medium uppercase tracking-wide text-slate-300">
                            {option.label}
                          </span>
                        </label>
                      </li>
                    );
                  })}
                </ul>
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
