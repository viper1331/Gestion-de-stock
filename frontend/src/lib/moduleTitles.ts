import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { fetchConfigEntries, type ConfigEntry } from "./config";

export const MODULE_TITLE_DEFAULTS: Record<string, string> = {
  barcode: "Codes-barres",
  clothing: "Inventaire habillement",
  suppliers: "Fournisseurs",
  dotations: "Dotations",
  pharmacy: "Pharmacie",
  vehicle_qrcodes: "QR codes véhicules",
  vehicle_inventory: "Inventaire véhicules",
  inventory_remise: "Inventaire remises"
};

export function getModuleTitleFromEntries(
  entries: ConfigEntry[] | undefined,
  moduleKey: string
): string {
  const override = entries?.find((entry) => entry.section === "modules" && entry.key === moduleKey);
  const trimmed = override?.value.trim();
  if (trimmed) {
    return trimmed;
  }
  return MODULE_TITLE_DEFAULTS[moduleKey] ?? moduleKey;
}

export function buildModuleTitleMap(entries: ConfigEntry[] | undefined): Record<string, string> {
  const map: Record<string, string> = { ...MODULE_TITLE_DEFAULTS };
  entries?.forEach((entry) => {
    if (entry.section === "modules") {
      const trimmed = entry.value.trim();
      if (trimmed) {
        map[entry.key] = trimmed;
      }
    }
  });
  return map;
}

export function useModuleTitle(moduleKey: string): string {
  const { data: entries = [] } = useQuery({
    queryKey: ["config", "global"],
    queryFn: fetchConfigEntries
  });

  return useMemo(() => getModuleTitleFromEntries(entries, moduleKey), [entries, moduleKey]);
}
