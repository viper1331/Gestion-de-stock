import { useMemo, useState } from "react";

import type { AriSessionStatus, AriSessionsFiltersState } from "../utils/ariSessionsFilter";
import { ariSessionStatusLabels } from "../utils/ariSessionsFilter";

type AriSessionsFiltersProps = {
  filters: AriSessionsFiltersState;
  onChange: (next: AriSessionsFiltersState) => void;
  onReset: () => void;
  availableCourses: string[];
  availableStatuses: AriSessionStatus[];
  totalCount: number;
  filteredCount: number;
  disabled?: boolean;
};

const formatDateInputValue = (date: Date) => date.toISOString().slice(0, 10);

export function AriSessionsFilters({
  filters,
  onChange,
  onReset,
  availableCourses,
  availableStatuses,
  totalCount,
  filteredCount,
  disabled = false
}: AriSessionsFiltersProps) {
  const [isExpanded, setIsExpanded] = useState(true);

  const statusOptions = useMemo(
    () => availableStatuses.map((status) => ({ value: status, label: ariSessionStatusLabels[status] })),
    [availableStatuses]
  );

  const handleFieldChange = (field: keyof AriSessionsFiltersState, value: string) => {
    onChange({
      ...filters,
      [field]: value
    });
  };

  const applyQuickRange = (days: number) => {
    const now = new Date();
    const start = new Date();
    start.setDate(now.getDate() - days + 1);
    onChange({
      ...filters,
      dateFrom: formatDateInputValue(start),
      dateTo: formatDateInputValue(now)
    });
  };

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-200">Filtres</h2>
          <p className="text-xs text-slate-400">
            {filteredCount} / {totalCount} séances
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            className="rounded-md border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
            onClick={onReset}
            disabled={disabled}
          >
            Réinitialiser
          </button>
          <button
            type="button"
            className="rounded-md border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200 hover:bg-slate-800 md:hidden"
            onClick={() => setIsExpanded((open) => !open)}
          >
            {isExpanded ? "Masquer" : "Afficher"}
          </button>
        </div>
      </div>

      <div className={`mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3 ${isExpanded ? "grid" : "hidden md:grid"}`}>
        <div className="space-y-2 rounded-lg border border-slate-800 bg-slate-950/40 p-3">
          <p className="text-xs uppercase tracking-wide text-slate-400">Date</p>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <label className="flex flex-col gap-1 text-xs text-slate-400">
              Du
              <input
                type="date"
                className="rounded-md border border-slate-700 bg-slate-900 px-3 py-1 text-sm text-slate-100"
                value={filters.dateFrom}
                onChange={(event) => handleFieldChange("dateFrom", event.target.value)}
                disabled={disabled}
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-slate-400">
              Au
              <input
                type="date"
                className="rounded-md border border-slate-700 bg-slate-900 px-3 py-1 text-sm text-slate-100"
                value={filters.dateTo}
                onChange={(event) => handleFieldChange("dateTo", event.target.value)}
                disabled={disabled}
              />
            </label>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
              onClick={() => applyQuickRange(1)}
              disabled={disabled}
            >
              Aujourd'hui
            </button>
            <button
              type="button"
              className="rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
              onClick={() => applyQuickRange(7)}
              disabled={disabled}
            >
              7 jours
            </button>
            <button
              type="button"
              className="rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
              onClick={() => applyQuickRange(30)}
              disabled={disabled}
            >
              30 jours
            </button>
          </div>
        </div>

        <div className="space-y-2 rounded-lg border border-slate-800 bg-slate-950/40 p-3">
          <p className="text-xs uppercase tracking-wide text-slate-400">Collaborateur</p>
          <input
            type="text"
            placeholder="Collaborateur…"
            className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
            value={filters.collaboratorQuery}
            onChange={(event) => handleFieldChange("collaboratorQuery", event.target.value)}
            disabled={disabled}
          />
        </div>

        <div className="space-y-2 rounded-lg border border-slate-800 bg-slate-950/40 p-3">
          <p className="text-xs uppercase tracking-wide text-slate-400">Parcours</p>
          <select
            className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
            value={filters.course}
            onChange={(event) => handleFieldChange("course", event.target.value)}
            disabled={disabled || availableCourses.length === 0}
          >
            <option value="">Tous</option>
            {availableCourses.map((course) => (
              <option key={course} value={course}>
                {course}
              </option>
            ))}
          </select>
        </div>

        <div className="space-y-2 rounded-lg border border-slate-800 bg-slate-950/40 p-3">
          <p className="text-xs uppercase tracking-wide text-slate-400">Durée (min)</p>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <input
              type="number"
              min="0"
              placeholder="Durée min"
              className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
              value={filters.durationMin}
              onChange={(event) => handleFieldChange("durationMin", event.target.value)}
              disabled={disabled}
            />
            <input
              type="number"
              min="0"
              placeholder="Durée max"
              className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
              value={filters.durationMax}
              onChange={(event) => handleFieldChange("durationMax", event.target.value)}
              disabled={disabled}
            />
          </div>
        </div>

        <div className="space-y-2 rounded-lg border border-slate-800 bg-slate-950/40 p-3">
          <p className="text-xs uppercase tracking-wide text-slate-400">Air (L/min)</p>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <input
              type="number"
              min="0"
              step="0.1"
              placeholder="Air min"
              className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
              value={filters.airMin}
              onChange={(event) => handleFieldChange("airMin", event.target.value)}
              disabled={disabled}
            />
            <input
              type="number"
              min="0"
              step="0.1"
              placeholder="Air max"
              className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
              value={filters.airMax}
              onChange={(event) => handleFieldChange("airMax", event.target.value)}
              disabled={disabled}
            />
          </div>
        </div>

        <div className="space-y-2 rounded-lg border border-slate-800 bg-slate-950/40 p-3">
          <p className="text-xs uppercase tracking-wide text-slate-400">Statut</p>
          <select
            className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
            value={filters.status}
            onChange={(event) => handleFieldChange("status", event.target.value)}
            disabled={disabled || statusOptions.length === 0}
          >
            <option value="">Tous</option>
            {statusOptions.map((status) => (
              <option key={status.value} value={status.value}>
                {status.label}
              </option>
            ))}
          </select>
        </div>
      </div>
    </section>
  );
}
