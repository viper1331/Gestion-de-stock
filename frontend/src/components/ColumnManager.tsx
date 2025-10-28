import { useEffect, useRef, useState } from "react";

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

  useEffect(() => {
    if (!isOpen) return;

    const handleClickOutside = (event: MouseEvent) => {
      if (!containerRef.current) return;
      if (!containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [isOpen]);

  const visibleCount = options.reduce(
    (count, option) => (visibility[option.key] !== false ? count + 1 : count),
    0
  );

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={() => setIsOpen((value) => !value)}
        className="rounded-md border border-slate-700 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-200 hover:bg-slate-800"
        title="Sélectionner les colonnes à afficher"
      >
        {title}
      </button>
      {isOpen ? (
        <div className="absolute right-0 z-20 mt-2 w-56 rounded-md border border-slate-800 bg-slate-950 p-3 shadow-xl">
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
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => onToggle(option.key)}
                        disabled={disableCheckbox}
                        className="h-4 w-4 rounded border-slate-700 bg-slate-900 text-indigo-500 focus:ring-indigo-500"
                      />
                      <span className="text-xs font-medium uppercase tracking-wide text-slate-300">{option.label}</span>
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
        </div>
      ) : null}
    </div>
  );
}
