import { FormEvent, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../lib/api";
import { useAuth } from "../auth/useAuth";
import { useModulePermissions } from "../permissions/useModulePermissions";
import { AppTextInput } from "components/AppTextInput";

interface Collaborator {
  id: number;
  full_name: string;
  department: string | null;
  email: string | null;
  phone: string | null;
}

interface CollaboratorPayload {
  full_name: string;
  department: string | null;
  email: string | null;
  phone: string | null;
}

export function CollaboratorsPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<Collaborator | null>(null);
  const [formMode, setFormMode] = useState<"create" | "edit">("create");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const modulePermissions = useModulePermissions({ enabled: Boolean(user) });
  const canView = user?.role === "admin" || modulePermissions.canAccess("dotations");
  const canEdit = user?.role === "admin" || modulePermissions.canAccess("dotations", "edit");

  const { data: collaborators = [], isFetching } = useQuery({
    queryKey: ["dotations", "collaborators"],
    queryFn: async () => {
      const response = await api.get<Collaborator[]>("/dotations/collaborators");
      return response.data;
    },
    enabled: canView
  });

  const createCollaborator = useMutation({
    mutationFn: async (payload: CollaboratorPayload) => {
      const response = await api.post<Collaborator>("/dotations/collaborators", payload);
      return response.data;
    },
    onSuccess: async () => {
      setMessage("Collaborateur ajouté.");
      await queryClient.invalidateQueries({ queryKey: ["dotations", "collaborators"] });
    },
    onError: () => setError("Impossible d'ajouter le collaborateur."),
    onSettled: () => setTimeout(() => setMessage(null), 4000)
  });

  const updateCollaborator = useMutation({
    mutationFn: async ({ id, payload }: { id: number; payload: CollaboratorPayload }) => {
      const response = await api.put<Collaborator>(`/dotations/collaborators/${id}`, payload);
      return response.data;
    },
    onSuccess: async () => {
      setMessage("Collaborateur mis à jour.");
      setSelected(null);
      setFormMode("create");
      await queryClient.invalidateQueries({ queryKey: ["dotations", "collaborators"] });
    },
    onError: () => setError("Impossible de mettre à jour."),
    onSettled: () => setTimeout(() => setMessage(null), 4000)
  });

  const deleteCollaborator = useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/dotations/collaborators/${id}`);
    },
    onSuccess: async () => {
      setMessage("Collaborateur supprimé.");
      setSelected(null);
      setFormMode("create");
      await queryClient.invalidateQueries({ queryKey: ["dotations", "collaborators"] });
    },
    onError: () => setError("Impossible de supprimer le collaborateur."),
    onSettled: () => setTimeout(() => setMessage(null), 4000)
  });

  const formValues = useMemo<CollaboratorPayload>(() => {
    if (formMode === "edit" && selected) {
      return {
        full_name: selected.full_name,
        department: selected.department,
        email: selected.email,
        phone: selected.phone
      };
    }
    return { full_name: "", department: "", email: "", phone: "" };
  }, [formMode, selected]);

  if (modulePermissions.isLoading && user?.role !== "admin") {
    return (
      <section className="space-y-4">
        <header className="space-y-1">
          <h2 className="text-2xl font-semibold text-white">Collaborateurs</h2>
          <p className="text-sm text-slate-400">Gérez les collaborateurs autorisés aux dotations.</p>
        </header>
        <p className="text-sm text-slate-400">Vérification des permissions...</p>
      </section>
    );
  }

  if (!canView) {
    return (
      <section className="space-y-4">
        <header className="space-y-1">
          <h2 className="text-2xl font-semibold text-white">Collaborateurs</h2>
          <p className="text-sm text-slate-400">Gérez les collaborateurs autorisés aux dotations.</p>
        </header>
        <p className="text-sm text-red-400">Accès refusé.</p>
      </section>
    );
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const payload: CollaboratorPayload = {
      full_name: (formData.get("full_name") as string).trim(),
      department: ((formData.get("department") as string) || "").trim() || null,
      email: ((formData.get("email") as string) || "").trim() || null,
      phone: ((formData.get("phone") as string) || "").trim() || null
    };
    if (!payload.full_name) {
      setError("Le nom est obligatoire.");
      return;
    }
    setMessage(null);
    setError(null);
    if (formMode === "edit" && selected) {
      await updateCollaborator.mutateAsync({ id: selected.id, payload });
    } else {
      await createCollaborator.mutateAsync(payload);
    }
    event.currentTarget.reset();
  };

  return (
    <section className="space-y-6">
      <header className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-white">Collaborateurs</h2>
          <p className="text-sm text-slate-400">Liste des collaborateurs éligibles aux dotations.</p>
        </div>
        {canEdit ? (
          <button
            type="button"
            onClick={() => {
              setSelected(null);
              setFormMode("create");
            }}
            className="rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400"
            title="Ajouter un nouveau collaborateur"
          >
            Nouveau collaborateur
          </button>
        ) : null}
      </header>
      {message ? <p className="text-sm text-emerald-300">{message}</p> : null}
      {error ? <p className="text-sm text-red-400">{error}</p> : null}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <div className="overflow-hidden rounded-lg border border-slate-800">
            <table className="min-w-full divide-y divide-slate-800">
              <thead className="bg-slate-900/60 text-xs uppercase tracking-wide text-slate-400">
                <tr>
                  <th className="px-4 py-3 text-left">Nom</th>
                  <th className="px-4 py-3 text-left">Service</th>
                  <th className="px-4 py-3 text-left">Email</th>
                  <th className="px-4 py-3 text-left">Téléphone</th>
                  {canEdit ? <th className="px-4 py-3 text-left">Actions</th> : null}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-900">
                {collaborators.map((collaborator) => (
                  <tr
                    key={collaborator.id}
                    className={`bg-slate-950 text-sm text-slate-100 ${
                      selected?.id === collaborator.id && formMode === "edit" ? "ring-1 ring-indigo-500" : ""
                    }`}
                  >
                    <td className="px-4 py-3 font-medium">{collaborator.full_name}</td>
                    <td className="px-4 py-3 text-slate-300">{collaborator.department ?? "-"}</td>
                    <td className="px-4 py-3 text-slate-300">{collaborator.email ?? "-"}</td>
                    <td className="px-4 py-3 text-slate-300">{collaborator.phone ?? "-"}</td>
                    {canEdit ? (
                      <td className="px-4 py-3 text-xs text-slate-200">
                        <div className="flex gap-2">
                          <button
                            type="button"
                            onClick={() => {
                              setSelected(collaborator);
                              setFormMode("edit");
                            }}
                            className="rounded bg-slate-800 px-2 py-1 hover:bg-slate-700"
                            title={`Modifier la fiche de ${collaborator.full_name}`}
                          >
                            Modifier
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              if (!window.confirm("Supprimer ce collaborateur ?")) {
                                return;
                              }
                              setMessage(null);
                              setError(null);
                              void deleteCollaborator.mutateAsync(collaborator.id);
                            }}
                            className="rounded bg-red-600 px-2 py-1 hover:bg-red-500"
                            title={`Supprimer ${collaborator.full_name} de la liste`}
                          >
                            Supprimer
                          </button>
                        </div>
                      </td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {isFetching ? <p className="mt-2 text-xs text-slate-400">Actualisation...</p> : null}
        </div>

        {canEdit ? (
          <aside className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <h3 className="text-sm font-semibold text-white">
              {formMode === "edit" ? "Modifier le collaborateur" : "Ajouter un collaborateur"}
            </h3>
            <form
              key={`${formMode}-${selected?.id ?? "new"}`}
              className="mt-3 space-y-3"
              onSubmit={handleSubmit}
            >
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="collab-full-name">
                  Nom complet
                </label>
                <AppTextInput
                  id="collab-full-name"
                  name="full_name"
                  defaultValue={formValues.full_name}
                  required
                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  title="Nom et prénom du collaborateur"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="collab-department">
                  Service
                </label>
                <AppTextInput
                  id="collab-department"
                  name="department"
                  defaultValue={formValues.department ?? ""}
                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  title="Service ou département d'affectation"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="collab-email">
                  Email
                </label>
                <AppTextInput
                  id="collab-email"
                  name="email"
                  type="email"
                  defaultValue={formValues.email ?? ""}
                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  title="Adresse e-mail professionnelle"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="collab-phone">
                  Téléphone
                </label>
                <AppTextInput
                  id="collab-phone"
                  name="phone"
                  defaultValue={formValues.phone ?? ""}
                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  title="Numéro de téléphone de contact"
                />
              </div>
              <div className="flex gap-2">
                <button
                  type="submit"
                  disabled={createCollaborator.isPending || updateCollaborator.isPending}
                  className="rounded-md bg-indigo-500 px-3 py-2 text-xs font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
                  title={
                    formMode === "edit"
                      ? "Enregistrer les informations du collaborateur"
                      : "Ajouter ce collaborateur aux dotations"
                  }
                >
                  {formMode === "edit"
                    ? updateCollaborator.isPending
                      ? "Mise à jour..."
                      : "Enregistrer"
                    : createCollaborator.isPending
                      ? "Ajout..."
                      : "Ajouter"}
                </button>
                {formMode === "edit" ? (
                  <button
                    type="button"
                    onClick={() => {
                      setSelected(null);
                      setFormMode("create");
                    }}
                    className="rounded-md bg-slate-800 px-3 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-700"
                    title="Annuler la modification en cours"
                  >
                    Annuler
                  </button>
                ) : null}
              </div>
            </form>
          </aside>
        ) : null}
      </div>
    </section>
  );
}

