export type CustomFieldType = "text" | "number" | "date" | "bool" | "select";

export interface CustomFieldDefinition {
  id: number;
  scope: string;
  key: string;
  label: string;
  field_type: CustomFieldType;
  required: boolean;
  default_json: unknown;
  options_json: unknown;
  is_active: boolean;
  sort_order: number;
}

export const CUSTOM_FIELD_SCOPES: Record<string, string> = {
  vehicles: "Véhicules",
  vehicle_items: "Matériel véhicules",
  remise_items: "Matériel remise",
  pharmacy_items: "Pharmacie",
  remise_lots: "Lots remise",
  pharmacy_lots: "Lots pharmacie"
};

export const CUSTOM_FIELD_TYPES: Array<{ value: CustomFieldType; label: string }> = [
  { value: "text", label: "Texte" },
  { value: "number", label: "Nombre" },
  { value: "date", label: "Date" },
  { value: "bool", label: "Booléen" },
  { value: "select", label: "Liste" }
];

export const sortCustomFields = (definitions: CustomFieldDefinition[]) =>
  [...definitions].sort((a, b) => {
    if (a.sort_order !== b.sort_order) return a.sort_order - b.sort_order;
    return a.label.localeCompare(b.label, "fr", { sensitivity: "base" });
  });

export const buildCustomFieldDefaults = (
  definitions: CustomFieldDefinition[],
  existing: Record<string, unknown> = {}
) => {
  const next: Record<string, unknown> = { ...existing };
  definitions.forEach((definition) => {
    if (next[definition.key] === undefined && definition.default_json !== undefined) {
      next[definition.key] = definition.default_json;
    }
  });
  return next;
};

export const normalizeCustomFieldOptions = (definition: CustomFieldDefinition) => {
  const raw = definition.options_json;
  if (Array.isArray(raw)) {
    return raw;
  }
  return [];
};
