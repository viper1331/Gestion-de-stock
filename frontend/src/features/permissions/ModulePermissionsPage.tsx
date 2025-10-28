import { FormEvent, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../lib/api";
import { useAuth } from "../auth/useAuth";

interface ModulePermissionEntry {
  id: number;
  user_id: number;
  module: string;
  can_view: boolean;
  can_edit: boolean;
}

interface UserEntry {
  id: number;
  username: string;
  role: string;
}

interface PermissionFormValues {
  user_id: number | null;
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
    user_id: null,
    module: "",
    can_view: true,
    can_edit: false
  });

  const { data: users = [], isFetching: isFetchingUsers } = useQuery({
    queryKey: ["users", "admin"],
    queryFn: async () => {
      const response = await api.get<UserEntry[]>("/users/");
      return response.data;
    },
    enabled: user?.role === "admin"
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

  useEffect(() => {
    if (user?.role !== "admin") {
      return;
    }
    if (formValues.user_id !== null) {
      return;
    }
    if (users.length === 0) {
      return;
    }
    const sortedUsers = [...users].sort((a, b) => a.username.localeCompare(b.username));
    setFormValues((prev) => ({ ...prev, user_id: sortedUsers[0]?.id ?? null }));
  }, [formValues.user_id, user?.role, users]);

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
    mutationFn: async ({ user_id, module }: { user_id: number; module: string }) => {
      await api.delete(`/permissions/modules/${user_id}/${module}`);
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

  const userLookup = useMemo(() => {
    return users.reduce<Record<number, UserEntry>>((acc, entry) => {
      acc[entry.id] = entry;
      return acc;
    }, {} as Record<number, UserEntry>);
  }, [users]);

  const groupedByUser = useMemo(() => {
    return permissions.reduce<Record<number, ModulePermissionEntry[]>>((acc, entry) => {
      if (!acc[entry.user_id]) {
        acc[entry.user_id] = [];
      }
      acc[entry.user_id].push(entry);
      acc[entry.user_id].sort((a, b) => a.module.localeCompare(b.module));
      return acc;
    }, {} as Record<number, ModulePermissionEntry[]>);
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
    if (formValues.user_id === null) {
      setError("Veuillez sélectionner un utilisateur.");
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
          Gérez les droits d'accès par utilisateur. Les administrateurs disposent de tous les accès par défaut.
        </p>
      </header>
      {isFetching || isFetchingUsers ? (
        <p className="text-sm text-slate-400">Chargement des données...</p>
      ) : null}
      {message ? <p className="text-sm text-emerald-300">{message}</p> : null}
      {error ? <p className="text-sm text-red-400">{error}</p> : null}

      <form className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-800 bg-slate-900 p-4" onSubmit={handleCreate}>
        <h3 className="text-sm font-semibold text-slate-200">Ajouter / modifier un module</h3>
        <label className="text-xs font-semibold uppercase tracking-wide text-slate-400">
          Utilisateur
          <select
            className="ml-2 rounded-md border border-slate-800 bg-slate-950 px-2 py-1 text-xs text-slate-100 focus:border-indigo-500 focus:outline-none"
            value={formValues.user_id ?? ""}
            onChange={(event) =>
              setFormValues((prev) => ({
                ...prev,
                user_id: event.target.value ? Number(event.target.value) : null
              }))
            }
          >
            <option value="" disabled>
              Sélectionner un utilisateur
            </option>
            {[...users]
              .sort((a, b) => a.username.localeCompare(b.username))
              .map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {entry.username} ({entry.role})
                </option>
              ))}
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
        {Object.entries(groupedByUser)
          .sort(([, entriesA], [, entriesB]) => {
            const userA = userLookup[entriesA[0]?.user_id ?? 0];
            const userB = userLookup[entriesB[0]?.user_id ?? 0];
            return (userA?.username ?? "").localeCompare(userB?.username ?? "");
          })
          .map(([userIdKey, entries]) => {
            const userId = Number(userIdKey);
            const userInfo = userLookup[userId];
            const disableEdits = userInfo?.role === "admin";
            return (
              <div key={userId} className="rounded-lg border border-slate-800 bg-slate-900">
                <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
                  <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-300">
                    Utilisateur : {userInfo?.username ?? "Inconnu"}
                  </h3>
                  {disableEdits ? (
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
                                user_id: entry.user_id,
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
                                user_id: entry.user_id,
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
                            await deletePermission.mutateAsync({ user_id: entry.user_id, module: entry.module });
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
          })}
        {permissions.length === 0 && !isFetching ? (
          <p className="text-sm text-slate-400">Aucune règle personnalisée définie.</p>
        ) : null}
      </div>
    </section>
  );
}

