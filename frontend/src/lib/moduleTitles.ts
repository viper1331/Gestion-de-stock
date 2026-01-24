import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { fetchConfigEntries, type ConfigEntry } from "./config";

export const MODULE_TITLE_DEFAULTS: Record<string, string> = {
  barcode: "Codes-barres",
  clothing: "Inventaire habillement",
  suppliers: "Fournisseurs",
  purchase_suggestions: "Suggestions de commandes",
  purchase_orders: "Bons de commande",
  collaborators: "Collaborateurs",
  dotations: "Dotations",
  reports: "Rapports",
  pharmacy: "Pharmacie",
  pharmacy_links: "Liens Pharmacie",
  messages: "Messagerie",
  vehicle_qr: "QR codes véhicules",
  vehicle_inventory: "Inventaire véhicules",
  inventory_remise: "Inventaire remises"
};

const MODULE_TITLE_ALIASES: Record<string, string> = {
  vehicle_qrcodes: "vehicle_qr",
  item_links: "pharmacy_links"
};

export function getModuleTitleFromEntries(
  entries: ConfigEntry[] | undefined,
  moduleKey: string
): string {
  const canonicalKey = MODULE_TITLE_ALIASES[moduleKey] ?? moduleKey;
  const override = entries?.find((entry) => entry.section === "modules" && entry.key === canonicalKey)
    ?? entries?.find((entry) => entry.section === "modules" && entry.key === moduleKey);
  const trimmed = override?.value.trim();
  if (trimmed) {
    return trimmed;
  }
  return MODULE_TITLE_DEFAULTS[canonicalKey] ?? moduleKey;
}

export function buildModuleTitleMap(entries: ConfigEntry[] | undefined): Record<string, string> {
  const map: Record<string, string> = { ...MODULE_TITLE_DEFAULTS };
  entries?.forEach((entry) => {
    if (entry.section === "modules") {
      const trimmed = entry.value.trim();
      if (trimmed) {
        const canonicalKey = MODULE_TITLE_ALIASES[entry.key] ?? entry.key;
        map[canonicalKey] = trimmed;
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
