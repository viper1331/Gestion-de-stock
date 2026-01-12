import { FormEvent, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../lib/api";
import { useAuth } from "../auth/useAuth";
import { useModulePermissions } from "../permissions/useModulePermissions";
import { useModuleTitle } from "../../lib/moduleTitles";
import { AppTextInput } from "components/AppTextInput";
import { AppTextArea } from "components/AppTextArea";
import { EditablePageLayout, type EditablePageBlock } from "../../components/EditablePageLayout";
import { EditableBlock } from "../../components/EditableBlock";

const DEFAULT_SUPPLIER_MODULE = "suppliers";

const SUPPLIER_MODULE_LABELS: Record<string, string> = {
  suppliers: "Habillement",
  pharmacy: "Pharmacie",
  inventory_remise: "Remise"
};

const SUPPLIER_MODULE_OPTIONS: Array<{ key: string; label: string }> = Object.entries(
  SUPPLIER_MODULE_LABELS
).map(([key, label]) => ({ key, label }));

function formatModuleLabel(module: string) {
  if (module in SUPPLIER_MODULE_LABELS) {
    return SUPPLIER_MODULE_LABELS[module];
  }
  return module
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

interface Supplier {
  id: number;
  name: string;
  contact_name: string | null;
  phone: string | null;
  email: string | null;
  address: string | null;
  modules: string[];
}

interface SupplierPayload {
  name: string;
  contact_name: string | null;
  phone: string | null;
  email: string | null;
  address: string | null;
  modules: string[];
}

export function SuppliersPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<Supplier | null>(null);
  const [formMode, setFormMode] = useState<"create" | "edit">("create");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const modulePermissions = useModulePermissions({ enabled: Boolean(user) });
  const canView = user?.role === "admin" || modulePermissions.canAccess("suppliers");
  const canEdit = user?.role === "admin" || modulePermissions.canAccess("suppliers", "edit");
  const moduleTitle = useModuleTitle("suppliers");

  const { data: suppliers = [], isFetching } = useQuery({
    queryKey: ["suppliers", "all"],
    queryFn: async () => {
      const response = await api.get<Supplier[]>("/suppliers/");
      return response.data;
    },
    enabled: canView
  });

  const moduleOptions = useMemo(() => {
    const labels = new Map<string, string>(SUPPLIER_MODULE_OPTIONS.map((option) => [option.key, option.label]));
    suppliers.forEach((supplier) => {
      supplier.modules.forEach((module) => {
        if (!labels.has(module)) {
          labels.set(module, formatModuleLabel(module));
        }
      });
    });
    return Array.from(labels.entries()).map(([key, label]) => ({ key, label }));
  }, [suppliers]);

  const createSupplier = useMutation({
    mutationFn: async (payload: SupplierPayload) => {
      await api.post("/suppliers/", payload);
    },
    onSuccess: async () => {
      setMessage("Fournisseur créé.");
      await queryClient.invalidateQueries({ queryKey: ["suppliers"] });
    },
    onError: () => setError("Impossible de créer le fournisseur."),
    onSettled: () => setTimeout(() => setMessage(null), 4000)
  });

  const updateSupplier = useMutation({
    mutationFn: async ({ id, payload }: { id: number; payload: SupplierPayload }) => {
      await api.put(`/suppliers/${id}`, payload);
    },
    onSuccess: async () => {
      setMessage("Fournisseur mis à jour.");
      setSelected(null);
      setFormMode("create");
      await queryClient.invalidateQueries({ queryKey: ["suppliers"] });
    },
    onError: () => setError("Impossible de mettre à jour le fournisseur."),
    onSettled: () => setTimeout(() => setMessage(null), 4000)
  });

  const deleteSupplier = useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/suppliers/${id}`);
    },
    onSuccess: async () => {
      setMessage("Fournisseur supprimé.");
      setSelected(null);
      setFormMode("create");
      await queryClient.invalidateQueries({ queryKey: ["suppliers"] });
    },
    onError: () => setError("Impossible de supprimer le fournisseur."),
    onSettled: () => setTimeout(() => setMessage(null), 4000)
  });

  const formValues = useMemo<SupplierPayload>(() => {
    if (formMode === "edit" && selected) {
      return {
        name: selected.name,
        contact_name: selected.contact_name,
        phone: selected.phone,
        email: selected.email,
        address: selected.address,
        modules: selected.modules.length > 0 ? selected.modules : [DEFAULT_SUPPLIER_MODULE]
      };
    }
    return {
      name: "",
      contact_name: "",
      phone: "",
      email: "",
      address: "",
      modules: [DEFAULT_SUPPLIER_MODULE]
    };
  }, [formMode, selected]);

  if (modulePermissions.isLoading && user?.role !== "admin") {
    return (
      <section className="space-y-4">
        <header className="space-y-1">
          <h2 className="text-2xl font-semibold text-white">{moduleTitle}</h2>
          <p className="text-sm text-slate-400">Gestion de vos contacts fournisseurs.</p>
        </header>
        <p className="text-sm text-slate-400">Vérification des permissions...</p>
      </section>
    );
  }

  if (!canView) {
    return (
      <section className="space-y-4">
        <header className="space-y-1">
          <h2 className="text-2xl font-semibold text-white">{moduleTitle}</h2>
          <p className="text-sm text-slate-400">Gestion de vos contacts fournisseurs.</p>
        </header>
        <p className="text-sm text-red-400">Accès refusé.</p>
      </section>
    );
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const payload: SupplierPayload = {
      name: (formData.get("name") as string).trim(),
      contact_name: ((formData.get("contact_name") as string) || "").trim() || null,
      phone: ((formData.get("phone") as string) || "").trim() || null,
      email: ((formData.get("email") as string) || "").trim() || null,
      address: ((formData.get("address") as string) || "").trim() || null,
      modules: (formData.getAll("modules") as string[]).map((module) => module.trim()).filter(Boolean)
    };
    if (!payload.name) {
      setError("Le nom est obligatoire.");
      return;
    }
    if (payload.modules.length === 0) {
      setError("Sélectionnez au moins un module concerné.");
      return;
    }
    setMessage(null);
    setError(null);
    if (formMode === "edit" && selected) {
      await updateSupplier.mutateAsync({ id: selected.id, payload });
    } else {
      await createSupplier.mutateAsync(payload);
    }
    event.currentTarget.reset();
  };

  const content = (
    <section className="space-y-6">
      <header className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-white">{moduleTitle}</h2>
          <p className="text-sm text-slate-400">Coordonnées et suivi des partenaires.</p>
        </div>
        {canEdit ? (
          <button
            type="button"
            onClick={() => {
              setSelected(null);
              setFormMode("create");
            }}
            className="rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400"
            title="Ajouter un nouveau fournisseur"
          >
            Nouveau fournisseur
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
                  <th className="px-4 py-3 text-left">Contact</th>
                  <th className="px-4 py-3 text-left">Téléphone</th>
                  <th className="px-4 py-3 text-left">Email</th>
                  <th className="px-4 py-3 text-left">Modules</th>
                  {canEdit ? <th className="px-4 py-3 text-left">Actions</th> : null}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-900">
                {suppliers.map((supplier) => (
                  <tr
                    key={supplier.id}
                    className={`bg-slate-950 text-sm text-slate-100 ${
                      selected?.id === supplier.id && formMode === "edit" ? "ring-1 ring-indigo-500" : ""
                    }`}
                  >
                    <td className="px-4 py-3 font-medium">{supplier.name}</td>
                    <td className="px-4 py-3 text-slate-300">{supplier.contact_name ?? "-"}</td>
                    <td className="px-4 py-3 text-slate-300">{supplier.phone ?? "-"}</td>
                    <td className="px-4 py-3 text-slate-300">{supplier.email ?? "-"}</td>
                    <td className="px-4 py-3 text-slate-300">
                      <div className="flex flex-wrap gap-1">
                        {supplier.modules.map((module) => (
                          <span
                            key={`${supplier.id}-${module}`}
                            className="rounded border border-slate-700 bg-slate-900 px-2 py-0.5 text-[11px] uppercase tracking-wide text-slate-200"
                          >
                            {formatModuleLabel(module)}
                          </span>
                        ))}
                      </div>
                    </td>
                    {canEdit ? (
                      <td className="px-4 py-3 text-xs text-slate-200">
                        <div className="flex gap-2">
                          <button
                            type="button"
                            onClick={() => {
                              setSelected(supplier);
                              setFormMode("edit");
                            }}
                            className="rounded bg-slate-800 px-2 py-1 hover:bg-slate-700"
                            title={`Modifier les informations de ${supplier.name}`}
                          >
                            Modifier
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              if (!window.confirm("Supprimer ce fournisseur ?")) {
                                return;
                              }
                              setMessage(null);
                              setError(null);
                              void deleteSupplier.mutateAsync(supplier.id);
                            }}
                            className="rounded bg-red-600 px-2 py-1 hover:bg-red-500"
                            title={`Supprimer le fournisseur ${supplier.name}`}
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
              {formMode === "edit" ? "Modifier le fournisseur" : "Ajouter un fournisseur"}
            </h3>
            <form
              key={`${formMode}-${selected?.id ?? "new"}`}
              className="mt-3 space-y-3"
              onSubmit={handleSubmit}
            >
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="supplier-name">
                  Nom de l'entreprise
                </label>
                <AppTextInput
                  id="supplier-name"
                  name="name"
                  defaultValue={formValues.name}
                  required
                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  title="Nom légal ou commercial du fournisseur"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="supplier-contact">
                  Contact principal
                </label>
                <AppTextInput
                  id="supplier-contact"
                  name="contact_name"
                  defaultValue={formValues.contact_name ?? ""}
                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  title="Nom de votre interlocuteur principal"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="supplier-phone">
                  Téléphone
                </label>
                <AppTextInput
                  id="supplier-phone"
                  name="phone"
                  defaultValue={formValues.phone ?? ""}
                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  title="Numéro de téléphone du fournisseur"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="supplier-email">
                  Email
                </label>
                <AppTextInput
                  id="supplier-email"
                  name="email"
                  type="email"
                  defaultValue={formValues.email ?? ""}
                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  title="Adresse e-mail de contact"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-300" htmlFor="supplier-address">
                  Adresse
                </label>
                <AppTextArea
                  id="supplier-address"
                  name="address"
                  defaultValue={formValues.address ?? ""}
                  rows={3}
                  className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
                  title="Adresse postale du fournisseur"
                />
              </div>
              <fieldset className="space-y-2">
                <legend className="text-xs font-semibold text-slate-300">Modules concernés</legend>
                <p className="text-[11px] text-slate-400">
                  Contrôle les sections de l'application où ce fournisseur est disponible.
                </p>
                <div className="flex flex-wrap gap-3">
                  {moduleOptions.map((option) => (
                    <label key={option.key} className="flex items-center gap-2 text-xs text-slate-200">
                      <AppTextInput
                        type="checkbox"
                        name="modules"
                        value={option.key}
                        defaultChecked={formValues.modules.includes(option.key)}
                        className="h-4 w-4 rounded border-slate-700 bg-slate-950 text-indigo-500 focus:ring-indigo-500"
                      />
                      {option.label}
                    </label>
                  ))}
                </div>
              </fieldset>
              <div className="flex gap-2">
                <button
                  type="submit"
                  disabled={createSupplier.isPending || updateSupplier.isPending}
                  className="rounded-md bg-indigo-500 px-3 py-2 text-xs font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
                  title={
                    formMode === "edit"
                      ? "Enregistrer les modifications du fournisseur"
                      : "Créer un nouveau fournisseur"
                  }
                >
                  {formMode === "edit"
                    ? updateSupplier.isPending
                      ? "Mise à jour..."
                      : "Enregistrer"
                    : createSupplier.isPending
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
                    title="Annuler l'édition en cours"
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

  const blocks: EditablePageBlock[] = [
    {
      id: "suppliers-main",
      title: "Fournisseurs",
      required: true,
      permissions: ["suppliers"],
      variant: "plain",
      defaultLayout: {
        lg: { x: 0, y: 0, w: 12, h: 24 },
        md: { x: 0, y: 0, w: 10, h: 24 },
        sm: { x: 0, y: 0, w: 6, h: 24 },
        xs: { x: 0, y: 0, w: 4, h: 24 }
      },
      render: () => (
        <EditableBlock id="suppliers-main">
          {content}
        </EditableBlock>
      )
    }
  ];

  return (
    <EditablePageLayout
      pageKey="module:suppliers"
      blocks={blocks}
      className="space-y-6"
    />
  );
}
