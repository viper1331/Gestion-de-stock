import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "../../lib/api";
import { AppTextInput } from "../../components/AppTextInput";
import { CustomLinksEditor } from "../../components/CustomLinksEditor";
import { useAuth } from "../auth/useAuth";
import { useModulePermissions } from "../permissions/useModulePermissions";

interface PharmacyItem {
  id: number;
  name: string;
  dosage: string | null;
  packaging: string | null;
  quantity: number;
  location: string | null;
}

export function PharmacyLinksPage() {
  const { user } = useAuth();
  const modulePermissions = useModulePermissions({ enabled: Boolean(user) });
  const canView = user?.role === "admin" || modulePermissions.canAccess("pharmacy_links");
  const canEdit = user?.role === "admin" || modulePermissions.canAccess("pharmacy_links", "edit");

  const [searchValue, setSearchValue] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const { data: items = [], isLoading } = useQuery({
    queryKey: ["pharmacy-items"],
    queryFn: async () => {
      const response = await api.get<PharmacyItem[]>("/pharmacy/");
      return response.data;
    },
    enabled: canView
  });

  const filteredItems = useMemo(() => {
    const term = searchValue.trim().toLowerCase();
    if (!term) return items;
    return items.filter((item) => {
      const content = `${item.name} ${item.dosage ?? ""} ${item.packaging ?? ""}`.toLowerCase();
      return content.includes(term);
    });
  }, [items, searchValue]);

  useEffect(() => {
    if (filteredItems.length === 0) {
      setSelectedId(null);
      return;
    }
    if (!selectedId || !filteredItems.some((item) => item.id === selectedId)) {
      setSelectedId(filteredItems[0].id);
    }
  }, [filteredItems, selectedId]);

  const selectedItem = filteredItems.find((item) => item.id === selectedId) ?? null;

  if (!canView) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300">
        Vous n'avez pas accès à la gestion des liens pharmacie.
      </div>
    );
  }

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900 dark:text-white">Liens Pharmacie</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Sélectionnez un article pour gérer les liens personnalisés.
          </p>
        </div>
        <AppTextInput
          value={searchValue}
          onChange={(event) => setSearchValue(event.target.value)}
          placeholder="Rechercher un article..."
          className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none sm:max-w-xs dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
        />
      </div>

      <div className="flex min-w-0 flex-col gap-6 lg:flex-row">
        <div className="flex min-w-0 flex-1 flex-col gap-3">
          <div className="rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <div className="border-b border-slate-200 px-4 py-3 text-sm font-semibold text-slate-700 dark:border-slate-800 dark:text-slate-200">
              Articles
            </div>
            <div className="max-h-[420px] overflow-auto">
              <table className="min-w-full text-left text-sm">
                <thead className="sticky top-0 bg-slate-50 text-xs uppercase text-slate-500 dark:bg-slate-950 dark:text-slate-400">
                  <tr>
                    <th className="px-4 py-2 font-semibold">Nom</th>
                    <th className="px-4 py-2 font-semibold">Quantité</th>
                    <th className="px-4 py-2 font-semibold">Localisation</th>
                  </tr>
                </thead>
                <tbody>
                  {isLoading ? (
                    <tr>
                      <td colSpan={3} className="px-4 py-4 text-center text-slate-500">
                        Chargement...
                      </td>
                    </tr>
                  ) : filteredItems.length === 0 ? (
                    <tr>
                      <td colSpan={3} className="px-4 py-4 text-center text-slate-500">
                        Aucun article trouvé.
                      </td>
                    </tr>
                  ) : (
                    filteredItems.map((item) => {
                      const isSelected = item.id === selectedId;
                      return (
                        <tr
                          key={item.id}
                          className={[
                            "cursor-pointer border-t border-slate-100 transition hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/60",
                            isSelected ? "bg-indigo-50 dark:bg-indigo-500/10" : ""
                          ].join(" ")}
                          onClick={() => setSelectedId(item.id)}
                        >
                          <td className="px-4 py-3 font-medium text-slate-800 dark:text-slate-100">
                            {item.name}
                            {item.dosage ? (
                              <div className="text-xs text-slate-500 dark:text-slate-400">{item.dosage}</div>
                            ) : null}
                          </td>
                          <td className="px-4 py-3 text-slate-600 dark:text-slate-300">{item.quantity}</td>
                          <td className="px-4 py-3 text-slate-600 dark:text-slate-300">
                            {item.location ?? "—"}
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div className="flex min-w-0 flex-1 flex-col gap-3">
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
            <h2 className="text-base font-semibold text-slate-900 dark:text-white">
              {selectedItem ? `Liens pour ${selectedItem.name}` : "Sélectionnez un article"}
            </h2>
            <div className="mt-4 min-w-0">
              {selectedItem ? (
                <CustomLinksEditor
                  module="pharmacy"
                  itemId={String(selectedItem.id)}
                  readonly={!canEdit}
                />
              ) : (
                <p className="text-sm text-slate-500 dark:text-slate-400">
                  Sélectionnez un article dans la liste pour afficher ses liens.
                </p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
