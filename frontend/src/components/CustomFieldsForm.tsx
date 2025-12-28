import { ChangeEvent } from "react";

import {
  CustomFieldDefinition,
  normalizeCustomFieldOptions,
  sortCustomFields
} from "../lib/customFields";

type CustomFieldValues = Record<string, unknown>;

interface CustomFieldsFormProps {
  definitions: CustomFieldDefinition[];
  values: CustomFieldValues;
  onChange: (next: CustomFieldValues) => void;
  disabled?: boolean;
}

export function CustomFieldsForm({
  definitions,
  values,
  onChange,
  disabled = false
}: CustomFieldsFormProps) {
  if (!definitions.length) {
    return null;
  }

  const handleValueChange =
    (definition: CustomFieldDefinition) =>
    (event: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
      const next = { ...values };
      if (definition.field_type === "bool") {
        if (event.target instanceof HTMLInputElement) {
          next[definition.key] = event.target.checked;
        } else {
          next[definition.key] = event.target.value === "true";
        }
      } else if (definition.field_type === "number") {
        const raw = event.target.value;
        next[definition.key] = raw === "" ? null : Number(raw);
      } else {
        next[definition.key] = event.target.value;
      }
      onChange(next);
    };

  return (
    <div className="space-y-3">
      {sortCustomFields(definitions).map((definition) => {
        const rawValue = values[definition.key];
        const id = `custom-field-${definition.key}`;
        const label = definition.required ? `${definition.label} *` : definition.label;
        if (definition.field_type === "bool") {
          return (
            <label key={definition.id} className="flex items-center gap-2 text-xs text-slate-300">
              <input
                id={id}
                type="checkbox"
                checked={Boolean(rawValue)}
                onChange={handleValueChange(definition)}
                disabled={disabled}
                className="h-4 w-4 rounded border-slate-600 bg-slate-800 text-blue-500"
              />
              <span>{label}</span>
            </label>
          );
        }
        if (definition.field_type === "select") {
          const options = normalizeCustomFieldOptions(definition);
          return (
            <label key={definition.id} className="block space-y-1">
              <span className="text-xs font-semibold text-slate-300">{label}</span>
              <select
                id={id}
                value={rawValue ? String(rawValue) : ""}
                onChange={handleValueChange(definition)}
                disabled={disabled}
                className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
              >
                <option value="">Sélectionner...</option>
                {options.map((option) => (
                  <option key={String(option)} value={String(option)}>
                    {String(option)}
                  </option>
                ))}
              </select>
            </label>
          );
        }
        return (
          <label key={definition.id} className="block space-y-1">
            <span className="text-xs font-semibold text-slate-300">{label}</span>
            <input
              id={id}
              type={definition.field_type === "date" ? "date" : definition.field_type === "number" ? "number" : "text"}
              value={rawValue === null || rawValue === undefined ? "" : String(rawValue)}
              onChange={handleValueChange(definition)}
              disabled={disabled}
              className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
            />
          </label>
        );
      })}
    </div>
  );
}
