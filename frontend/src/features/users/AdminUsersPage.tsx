import { FormEvent, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../lib/api";
import { useAuth } from "../auth/useAuth";
import { AppTextInput } from "components/AppTextInput";
import { EditablePageLayout, type EditablePageBlock } from "../../components/EditablePageLayout";
import { EditableBlock } from "../../components/EditableBlock";

type UserRole = "admin" | "user";

const SITE_OPTIONS = [
  { value: "JLL", label: "JLL" },
  { value: "GSM", label: "GSM" },
  { value: "ST_ELOIS", label: "St Elois" },
  { value: "CENTRAL_ENTITY", label: "Central Entity" }
];

interface UserEntry {
  id: number;
  username: string;
  role: UserRole;
  is_active: boolean;
  site_key: string;
  status: "active" | "pending" | "rejected" | "disabled";
}

interface CreateUserForm {
  username: string;
  password: string;
  role: UserRole;
  site_key: string;
}

interface UserDraft {
  role: UserRole;
  password: string;
  is_active: boolean;
  site_key: string;
}

export function AdminUsersPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [createForm, setCreateForm] = useState<CreateUserForm>({
    username: "",
    password: "",
    role: "user",
    site_key: "JLL"
  });
  const [drafts, setDrafts] = useState<Record<number, UserDraft>>({});
  const [showPendingOnly, setShowPendingOnly] = useState(false);

  const { data: users = [], isFetching } = useQuery({
    queryKey: ["admin-users"],
    queryFn: async () => {
      const response = await api.get<UserEntry[]>("/users/?include_pending=true");
      return response.data;
    },
    enabled: user?.role === "admin"
  });

  const clearMessageLater = () => {
    window.setTimeout(() => {
      setMessage(null);
      setError(null);
    }, 4000);
  };

  const createUser = useMutation({
    mutationFn: async (payload: CreateUserForm) => {
      await api.post("/users/", payload);
    },
    onSuccess: async () => {
      setMessage("Utilisateur créé.");
      setError(null);
      setCreateForm({ username: "", password: "", role: "user", site_key: "JLL" });
      setDrafts({});
      await queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      clearMessageLater();
    },
    onError: () => {
      setError("Impossible de créer l'utilisateur.");
      clearMessageLater();
    }
  });

  const updateUser = useMutation({
    mutationFn: async ({ id, payload }: { id: number; payload: Partial<UserDraft> }) => {
      await api.put(`/users/${id}`, payload);
    },
    onSuccess: async (_data, variables) => {
      setMessage("Utilisateur mis à jour.");
      setError(null);
      setDrafts((prev) => {
        const next = { ...prev };
        delete next[variables.id];
        return next;
      });
      await queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      clearMessageLater();
    },
    onError: () => {
      setError("Impossible de mettre à jour l'utilisateur.");
      clearMessageLater();
    }
  });

  const deleteUser = useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/users/${id}`);
    },
    onSuccess: async () => {
      setMessage("Utilisateur supprimé.");
      setError(null);
      await queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      clearMessageLater();
    },
    onError: () => {
      setError("Impossible de supprimer l'utilisateur.");
      clearMessageLater();
    }
  });

  const approveUser = useMutation({
    mutationFn: async (id: number) => {
      await api.post(`/users/${id}/approve`);
    },
    onSuccess: async () => {
      setMessage("Compte approuvé.");
      setError(null);
      await queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      clearMessageLater();
    },
    onError: () => {
      setError("Impossible d'approuver ce compte.");
      clearMessageLater();
    }
  });

  const rejectUser = useMutation({
    mutationFn: async (id: number) => {
      await api.post(`/users/${id}/reject`);
    },
    onSuccess: async () => {
      setMessage("Compte refusé.");
      setError(null);
      await queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      clearMessageLater();
    },
    onError: () => {
      setError("Impossible de refuser ce compte.");
      clearMessageLater();
    }
  });

  const draftsWithDefaults = useMemo(() => {
    return users.reduce<Record<number, UserDraft>>((acc, entry) => {
      acc[entry.id] = drafts[entry.id] ?? {
        role: entry.role,
        password: "",
        is_active: entry.is_active,
        site_key: entry.site_key
      };
      return acc;
    }, {});
  }, [drafts, users]);

  if (user?.role !== "admin") {
    return (
      <section className="space-y-4">
        <header className="space-y-1">
          <h2 className="text-2xl font-semibold text-white">Utilisateurs</h2>
          <p className="text-sm text-slate-400">Seuls les administrateurs peuvent consulter cette page.</p>
        </header>
        <p className="text-sm text-red-400">Accès interdit.</p>
      </section>
    );
  }

  const handleCreate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const username = createForm.username.trim();
    const password = createForm.password;

    if (!username) {
      setError("Veuillez renseigner un identifiant.");
      clearMessageLater();
      return;
    }

    if (password.length < 8) {
      setError("Le mot de passe doit contenir au moins 8 caractères.");
      clearMessageLater();
      return;
    }

    setMessage(null);
    setError(null);
    await createUser.mutateAsync({
      username,
      password,
      role: createForm.role,
      site_key: createForm.site_key
    });
  };

  const handleDraftChange = (entry: UserEntry, partial: Partial<UserDraft>) => {
    setDrafts((prev) => {
      const base = prev[entry.id] ?? {
        role: entry.role,
        password: "",
        is_active: entry.is_active,
        site_key: entry.site_key
      };
      return {
        ...prev,
        [entry.id]: { ...base, ...partial }
      };
    });
  };

  const hasPendingChanges = (entry: UserEntry) => {
    const draft = draftsWithDefaults[entry.id];
    return (
      draft.role !== entry.role ||
      draft.is_active !== entry.is_active ||
      (draft.password?.length ?? 0) > 0 ||
      draft.site_key !== entry.site_key
    );
  };

  const handleSave = async (entry: UserEntry) => {
    const draft = draftsWithDefaults[entry.id];
    const payload: Partial<UserDraft> = {};
    if (draft.role !== entry.role) {
      payload.role = draft.role;
    }
    if (draft.is_active !== entry.is_active) {
      payload.is_active = draft.is_active;
    }
    if (draft.password) {
      payload.password = draft.password;
    }
    if (draft.site_key !== entry.site_key) {
      payload.site_key = draft.site_key;
    }
    if (Object.keys(payload).length === 0) {
      setMessage("Aucune modification à enregistrer.");
      clearMessageLater();
      return;
    }
    setMessage(null);
    setError(null);
    await updateUser.mutateAsync({ id: entry.id, payload });
  };

  const handleDelete = async (entry: UserEntry) => {
    if (entry.username === "admin") {
      setError("L'utilisateur administrateur par défaut ne peut pas être supprimé.");
      clearMessageLater();
      return;
    }
    const confirmed = window.confirm(
      `Supprimer l'utilisateur ${entry.username} ? Cette action est irréversible.`
    );
    if (!confirmed) {
      return;
    }
    setMessage(null);
    setError(null);
    await deleteUser.mutateAsync(entry.id);
  };

  const isProcessing =
    createUser.isPending ||
    updateUser.isPending ||
    deleteUser.isPending ||
    approveUser.isPending ||
    rejectUser.isPending;

  const filteredUsers = showPendingOnly
    ? users.filter((entry) => entry.status === "pending")
    : users;

  const content = (
    <section className="space-y-6">
      <header className="space-y-1">
        <h2 className="text-2xl font-semibold text-white">Gestion des utilisateurs</h2>
        <p className="text-sm text-slate-400">
          Créez de nouveaux comptes et ajustez les droits des membres de votre équipe.
        </p>
        <label className="flex items-center gap-2 text-sm text-slate-300">
          <AppTextInput
            type="checkbox"
            checked={showPendingOnly}
            onChange={(event) => setShowPendingOnly(event.target.checked)}
            title="Afficher uniquement les comptes en attente"
          />
          Afficher les demandes en attente
        </label>
      </header>
      {isFetching ? <p className="text-sm text-slate-400">Chargement des utilisateurs...</p> : null}
      {message ? <p className="text-sm text-emerald-300">{message}</p> : null}
      {error ? <p className="text-sm text-red-400">{error}</p> : null}

      <form
        className="flex flex-wrap items-end gap-3 rounded-lg border border-slate-800 bg-slate-900 p-4"
        onSubmit={handleCreate}
      >
        <div className="flex flex-1 flex-col">
          <label className="text-xs font-semibold uppercase tracking-wide text-slate-400">Email</label>
          <AppTextInput
            className="mt-1 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            value={createForm.username}
            onChange={(event) => setCreateForm((prev) => ({ ...prev, username: event.target.value }))}
            placeholder="ex: jdupont@entreprise.fr"
            title="Email de connexion du nouvel utilisateur"
          />
        </div>
        <div className="flex flex-1 flex-col">
          <label className="text-xs font-semibold uppercase tracking-wide text-slate-400">Mot de passe</label>
          <AppTextInput
            className="mt-1 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            value={createForm.password}
            type="password"
            onChange={(event) => setCreateForm((prev) => ({ ...prev, password: event.target.value }))}
            placeholder="Minimum 8 caractères"
            title="Définissez un mot de passe temporaire pour ce compte"
          />
        </div>
        <label className="flex flex-col text-xs font-semibold uppercase tracking-wide text-slate-400">
          Rôle
          <select
            className="mt-1 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            value={createForm.role}
            onChange={(event) =>
              setCreateForm((prev) => ({ ...prev, role: event.target.value as UserRole }))
            }
            title="Choisissez le niveau d'accès du nouvel utilisateur"
          >
            <option value="user">Utilisateur</option>
            <option value="admin">Administrateur</option>
          </select>
        </label>
        <label className="flex flex-col text-xs font-semibold uppercase tracking-wide text-slate-400">
          Site
          <select
            className="mt-1 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
            value={createForm.site_key}
            onChange={(event) =>
              setCreateForm((prev) => ({ ...prev, site_key: event.target.value }))
            }
            title="Choisissez le site associé au nouvel utilisateur"
          >
            {SITE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="submit"
          disabled={createUser.isPending || isProcessing}
          className="rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
          title="Créer le compte utilisateur"
        >
          {createUser.isPending ? "Création..." : "Créer"}
        </button>
      </form>

      <div className="overflow-x-auto rounded-lg border border-slate-800">
        <table className="min-w-full divide-y divide-slate-800">
          <thead className="bg-slate-900/60 text-xs uppercase tracking-wide text-slate-400">
            <tr>
              <th className="px-4 py-2 text-left">Email</th>
              <th className="px-4 py-2 text-left">Rôle</th>
              <th className="px-4 py-2 text-left">Site</th>
              <th className="px-4 py-2 text-left">Statut</th>
              <th className="px-4 py-2 text-left">Activation</th>
              <th className="px-4 py-2 text-left">Mot de passe</th>
              <th className="px-4 py-2 text-left">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800 bg-slate-900 text-sm text-slate-200">
            {filteredUsers.map((entry) => {
              const draft = draftsWithDefaults[entry.id];
              const statusLabel = {
                active: "Actif",
                pending: "En attente",
                rejected: "Refusé",
                disabled: "Désactivé"
              }[entry.status];
              const statusClasses = {
                active: "bg-emerald-500/10 text-emerald-200 border-emerald-500/30",
                pending: "bg-amber-500/10 text-amber-200 border-amber-500/30",
                rejected: "bg-red-500/10 text-red-200 border-red-500/30",
                disabled: "bg-slate-500/10 text-slate-300 border-slate-500/30"
              }[entry.status];
              return (
                <tr key={entry.id}>
                  <td className="px-4 py-3 font-medium text-white">{entry.username}</td>
                  <td className="px-4 py-3">
                    <select
                      className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
                      value={draft.role}
                      onChange={(event) =>
                        handleDraftChange(entry, { role: event.target.value as UserRole })
                      }
                      title="Modifier le rôle attribué à cet utilisateur"
                    >
                      <option value="user">Utilisateur</option>
                      <option value="admin">Administrateur</option>
                    </select>
                  </td>
                  <td className="px-4 py-3">
                    <select
                      className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
                      value={draft.site_key}
                      onChange={(event) =>
                        handleDraftChange(entry, { site_key: event.target.value })
                      }
                      title="Modifier le site attribué à cet utilisateur"
                    >
                      {SITE_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center rounded-full border px-2 py-1 text-xs ${statusClasses}`}>
                      {statusLabel}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <label className="flex items-center gap-2 text-xs text-slate-300">
                      <AppTextInput
                        type="checkbox"
                        checked={draft.is_active}
                        onChange={(event) =>
                          handleDraftChange(entry, { is_active: event.target.checked })
                        }
                        disabled={entry.status !== "active" && entry.status !== "disabled"}
                        title="Activer ou désactiver le compte"
                      />
                      {draft.is_active ? "Actif" : "Désactivé"}
                    </label>
                  </td>
                  <td className="px-4 py-3">
                    <AppTextInput
                      type="password"
                      value={draft.password}
                      onChange={(event) => handleDraftChange(entry, { password: event.target.value })}
                      placeholder="Laisser vide pour ne pas changer"
                      className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                      title="Définissez un nouveau mot de passe si nécessaire"
                    />
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-2">
                      {entry.status === "pending" ? (
                        <>
                          <button
                            type="button"
                            onClick={() => approveUser.mutateAsync(entry.id)}
                            disabled={approveUser.isPending}
                            className="rounded-md bg-emerald-500 px-3 py-2 text-xs font-semibold text-white shadow hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-70"
                            title="Approuver ce compte"
                          >
                            {approveUser.isPending ? "Approbation..." : "Approuver"}
                          </button>
                          <button
                            type="button"
                            onClick={() => rejectUser.mutateAsync(entry.id)}
                            disabled={rejectUser.isPending}
                            className="rounded-md bg-amber-500 px-3 py-2 text-xs font-semibold text-white shadow hover:bg-amber-400 disabled:cursor-not-allowed disabled:opacity-70"
                            title="Refuser ce compte"
                          >
                            {rejectUser.isPending ? "Refus..." : "Refuser"}
                          </button>
                        </>
                      ) : null}
                      <button
                        type="button"
                        onClick={() => handleSave(entry)}
                        disabled={!hasPendingChanges(entry) || updateUser.isPending}
                        className="rounded-md bg-indigo-500 px-3 py-2 text-xs font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
                        title={
                          hasPendingChanges(entry)
                            ? "Enregistrer les modifications"
                            : "Aucune modification à sauvegarder"
                        }
                      >
                        {updateUser.isPending ? "Enregistrement..." : "Enregistrer"}
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDelete(entry)}
                        disabled={deleteUser.isPending || entry.username === "admin"}
                        className="rounded-md bg-red-500 px-3 py-2 text-xs font-semibold text-white shadow hover:bg-red-400 disabled:cursor-not-allowed disabled:opacity-70"
                        title={
                          entry.username === "admin"
                            ? "Le compte administrateur par défaut ne peut pas être supprimé"
                            : "Supprimer cet utilisateur"
                        }
                      >
                        {deleteUser.isPending ? "Suppression..." : "Supprimer"}
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
            {filteredUsers.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-sm text-slate-400">
                  Aucun utilisateur trouvé.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  );

  const blocks: EditablePageBlock[] = [
    {
      id: "admin-users-main",
      title: "Utilisateurs",
      required: true,
      permissions: ["admin"],
      defaultLayout: {
        lg: { x: 0, y: 0, w: 12, h: 24 },
        md: { x: 0, y: 0, w: 10, h: 24 },
        sm: { x: 0, y: 0, w: 6, h: 24 },
        xs: { x: 0, y: 0, w: 4, h: 24 }
      },
      variant: "plain",
      render: () => (
        <EditableBlock id="admin-users-main">
          {content}
        </EditableBlock>
      )
    }
  ];

  return (
    <EditablePageLayout pageKey="admin:users" blocks={blocks} className="space-y-6" />
  );
}
