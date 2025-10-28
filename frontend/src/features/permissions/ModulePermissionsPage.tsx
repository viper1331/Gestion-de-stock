import { FormEvent, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../lib/api";
import { useAuth } from "../auth/useAuth";

interface ModulePermissionEntry {
  id: number;
  role: string;
  module: string;
  can_view: boolean;
  can_edit: boolean;
}

interface PermissionFormValues {
  role: string;
  module: string;
  can_view: boolean;
  can_edit: boolean;
}

export function ModulePermissionsPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [formValues, setFormValues] = useState<PermissionFormValues>({
    role: "user",
    module: "",
    can_view: true,
    can_edit: false
  });

  const {
    data: permissions = [],
    isFetching
  } = useQuery({
    queryKey: ["module-permissions", "admin"],
    queryFn: async () => {
      const response = await api.get<ModulePermissionEntry[]>("/permissions/modules");
      return response.data;
    },
    enabled: user?.role === "admin"
  });

  const upsertPermission = useMutation({
    mutationFn: async (payload: PermissionFormValues) => {
      await api.put("/permissions/modules", payload);
    },
    onSuccess: async () => {
      setMessage("Droits enregistrés.");
      await queryClient.invalidateQueries({ queryKey: ["module-permissions", "admin"] });
    },
    onError: () => setError("Impossible d'enregistrer les droits."),
    onSettled: () => {
      setTimeout(() => setMessage(null), 4000);
    }
  });

  const deletePermission = useMutation({
    mutationFn: async ({ role, module }: { role: string; module: string }) => {
      await api.delete(`/permissions/modules/${role}/${module}`);
    },
    onSuccess: async () => {
      setMessage("Droits supprimés.");
      await queryClient.invalidateQueries({ queryKey: ["module-permissions", "admin"] });
    },
    onError: () => setError("Impossible de supprimer les droits."),
    onSettled: () => {
      setTimeout(() => setMessage(null), 4000);
    }
  });

  const groupedByRole = useMemo(() => {
    return permissions.reduce<Record<string, ModulePermissionEntry[]>>((acc, entry) => {
      if (!acc[entry.role]) {
        acc[entry.role] = [];
      }
      acc[entry.role].push(entry);
      acc[entry.role].sort((a, b) => a.module.localeCompare(b.module));
      return acc;
    }, {});
  }, [permissions]);

  if (user?.role !== "admin") {
    return (
      <section className="space-y-4">
        <header className="space-y-1">
          <h2 className="text-2xl font-semibold text-white">Permissions</h2>
          <p className="text-sm text-slate-400">Seuls les administrateurs peuvent consulter cette page.</p>
        </header>
        <p className="text-sm text-red-400">Accès interdit.</p>
      </section>
    );
  }

  const handleCreate = async (event: FormEvent) => {
    event.preventDefault();
    if (!formValues.module.trim()) {
      setError("Veuillez indiquer un nom de module.");
      return;
    }
    setMessage(null);
    setError(null);
    await upsertPermission.mutateAsync({
      ...formValues,
      module: formValues.module.trim()
    });
    setFormValues((prev) => ({ ...prev, module: "" }));
  };

  const isProcessing = upsertPermission.isPending || deletePermission.isPending;

  return (
    <section className="space-y-6">
      <header className="space-y-1">
        <h2 className="text-2xl font-semibold text-white">Permissions des modules</h2>
        <p className="text-sm text-slate-400">
          Gérez les droits d'accès par rôle. Les administrateurs disposent de tous les accès par défaut.
        </p>
      </header>
      {isFetching ? <p className="text-sm text-slate-400">Chargement des permissions...</p> : null}
      {message ? <p className="text-sm text-emerald-300">{message}</p> : null}
      {error ? <p className="text-sm text-red-400">{error}</p> : null}

      <form className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-800 bg-slate-900 p-4" onSubmit={handleCreate}>
        <h3 className="text-sm font-semibold text-slate-200">Ajouter / modifier un module</h3>
        <label className="text-xs font-semibold uppercase tracking-wide text-slate-400">
          Rôle
          <select
            className="ml-2 rounded-md border border-slate-800 bg-slate-950 px-2 py-1 text-xs text-slate-100 focus:border-indigo-500 focus:outline-none"
            value={formValues.role}
            onChange={(event) => setFormValues((prev) => ({ ...prev, role: event.target.value }))}
          >
            <option value="admin">admin</option>
            <option value="user">user</option>
          </select>
        </label>
        <label className="flex flex-1 flex-col text-xs font-semibold uppercase tracking-wide text-slate-400">
          Module
          <input
            value={formValues.module}
            onChange={(event) => setFormValues((prev) => ({ ...prev, module: event.target.value }))}
            placeholder="ex: suppliers"
            className="mt-1 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
          />
        </label>
        <label className="flex items-center gap-2 text-xs text-slate-300">
          <input
            type="checkbox"
            checked={formValues.can_view}
            onChange={(event) =>
              setFormValues((prev) => ({
                ...prev,
                can_view: event.target.checked,
                can_edit: event.target.checked ? prev.can_edit : false
              }))
            }
          />
          Lecture
        </label>
        <label className="flex items-center gap-2 text-xs text-slate-300">
          <input
            type="checkbox"
            checked={formValues.can_edit}
            onChange={(event) =>
              setFormValues((prev) => ({
                ...prev,
                can_view: event.target.checked ? true : prev.can_view,
                can_edit: event.target.checked
              }))
            }
          />
          Écriture
        </label>
        <button
          type="submit"
          disabled={isProcessing}
          className="rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
        >
          {upsertPermission.isPending ? "Enregistrement..." : "Enregistrer"}
        </button>
      </form>

      <div className="space-y-6">
        {Object.entries(groupedByRole).map(([role, entries]) => (
          <div key={role} className="rounded-lg border border-slate-800 bg-slate-900">
            <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
              <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-300">Rôle : {role}</h3>
              {role === "admin" ? (
                <span className="text-xs text-slate-400">Accès illimités par défaut</span>
              ) : null}
            </div>
            <table className="min-w-full divide-y divide-slate-800">
              <thead className="bg-slate-900/60 text-xs uppercase tracking-wide text-slate-400">
                <tr>
                  <th className="px-4 py-2 text-left">Module</th>
                  <th className="px-4 py-2 text-left">Lecture</th>
                  <th className="px-4 py-2 text-left">Écriture</th>
                  <th className="px-4 py-2 text-left">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-900">
                {entries.map((entry) => {
                  const disableEdits = role === "admin";
                  return (
                    <tr key={entry.id} className="bg-slate-950 text-sm text-slate-100">
                      <td className="px-4 py-2 font-medium">{entry.module}</td>
                      <td className="px-4 py-2">
                        <label className="inline-flex items-center gap-2 text-xs">
                          <input
                            type="checkbox"
                            checked={entry.can_view}
                            disabled={disableEdits || isProcessing}
                            onChange={async (event) => {
                              setMessage(null);
                              setError(null);
                              const nextCanView = event.target.checked;
                              await upsertPermission.mutateAsync({
                                role,
                                module: entry.module,
                                can_view: nextCanView,
                                can_edit: nextCanView ? entry.can_edit : false
                              });
                            }}
                          />
                          Autorisé
                        </label>
                      </td>
                      <td className="px-4 py-2">
                        <label className="inline-flex items-center gap-2 text-xs">
                          <input
                            type="checkbox"
                            checked={entry.can_edit}
                            disabled={disableEdits || isProcessing}
                            onChange={async (event) => {
                              setMessage(null);
                              setError(null);
                              await upsertPermission.mutateAsync({
                                role,
                                module: entry.module,
                                can_view: event.target.checked ? true : entry.can_view,
                                can_edit: event.target.checked
                              });
                            }}
                          />
                          Autorisé
                        </label>
                      </td>
                      <td className="px-4 py-2 text-xs">
                        <button
                          type="button"
                          disabled={disableEdits || isProcessing}
                          onClick={async () => {
                            if (!window.confirm("Supprimer cette règle ?")) {
                              return;
                            }
                            setMessage(null);
                            setError(null);
                            await deletePermission.mutateAsync({ role, module: entry.module });
                          }}
                          className="rounded bg-red-600 px-3 py-1 font-semibold text-white hover:bg-red-500 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          Supprimer
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ))}
        {permissions.length === 0 && !isFetching ? (
          <p className="text-sm text-slate-400">Aucune règle personnalisée définie.</p>
        ) : null}
      </div>
    </section>
  );
}

