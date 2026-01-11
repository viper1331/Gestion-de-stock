import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";

import { api } from "../../lib/api";
import { useAuth } from "../auth/useAuth";
import { useModulePermissions } from "../permissions/useModulePermissions";
import { AppTextInput } from "components/AppTextInput";
import {
  EditablePageLayout,
  type EditableLayoutSet,
  type EditablePageBlock
} from "../../components/EditablePageLayout";

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

interface BulkImportRow {
  full_name: string;
  department: string | null;
  email: string | null;
  phone: string | null;
}

interface BulkImportPayload {
  mode: "create" | "upsert" | "skip_duplicates";
  rows: BulkImportRow[];
}

interface BulkImportError {
  rowIndex: number;
  message: string;
}

interface BulkImportResult {
  created: number;
  updated: number;
  skipped: number;
  errors: BulkImportError[];
}

type ImportStep = "source" | "preview" | "mapping" | "validate";

type MappingState = {
  full_name: number | null;
  department: number | null;
  email: number | null;
  phone: number | null;
};

let xlsxModulePromise: Promise<typeof import("xlsx")> | null = null;

const loadXlsxModule = async () => {
  if (!xlsxModulePromise) {
    xlsxModulePromise = import("xlsx");
  }
  return xlsxModulePromise;
};

export function CollaboratorsPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<Collaborator | null>(null);
  const [formMode, setFormMode] = useState<"create" | "edit">("create");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isImportOpen, setIsImportOpen] = useState(false);
  const [importStep, setImportStep] = useState<ImportStep>("source");
  const [importRows, setImportRows] = useState<string[][]>([]);
  const [importSourceName, setImportSourceName] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [pasteContent, setPasteContent] = useState("");
  const [hasHeaders, setHasHeaders] = useState(true);
  const [mapping, setMapping] = useState<MappingState>({
    full_name: null,
    department: null,
    email: null,
    phone: null
  });
  const [importMode, setImportMode] = useState<"skip_duplicates" | "upsert">("skip_duplicates");
  const [importError, setImportError] = useState<string | null>(null);
  const [importResult, setImportResult] = useState<BulkImportResult | null>(null);

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const pasteRef = useRef<HTMLTextAreaElement | null>(null);

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

  const bulkImportCollaborators = useMutation({
    mutationFn: async (payload: BulkImportPayload) => {
      const response = await api.post<BulkImportResult>("/dotations/collaborators/bulk-import", payload);
      return response.data;
    },
    onSuccess: async (data) => {
      setImportResult(data);
      setMessage(
        `Import terminé : ${data.created} créés${data.updated ? `, ${data.updated} mis à jour` : ""}.`
      );
      await queryClient.invalidateQueries({ queryKey: ["dotations", "collaborators"] });
    },
    onError: () => setImportError("Impossible d'importer les collaborateurs."),
    onSettled: () => setTimeout(() => setMessage(null), 5000)
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

  const importHeaders = useMemo(() => deriveHeaders(importRows, hasHeaders), [importRows, hasHeaders]);
  const importDataRows = useMemo(
    () => (hasHeaders ? importRows.slice(1) : importRows),
    [importRows, hasHeaders]
  );
  const isTemplateMatch = useMemo(
    () => hasHeaders && headersMatchTemplate(importHeaders),
    [hasHeaders, importHeaders]
  );
  const autoMapping = useMemo(() => buildAutoMapping(importHeaders), [importHeaders]);

  const [previewFilter, setPreviewFilter] = useState("");
  const importSummary = useMemo(
    () => summarizeImportRows(importDataRows, mapping, hasHeaders),
    [importDataRows, mapping, hasHeaders]
  );
  const filteredImportRows = useMemo(() => {
    const query = previewFilter.trim().toLowerCase();
    if (!query) {
      return importDataRows;
    }

    return importDataRows.filter((row) =>
      row.some((cell) => (cell ?? "").toString().toLowerCase().includes(query))
    );
  }, [importDataRows, previewFilter]);

  useEffect(() => {
    if (!importHeaders.length) {
      setMapping({ full_name: null, department: null, email: null, phone: null });
      return;
    }
    setMapping(autoMapping);
  }, [autoMapping, importHeaders.length]);

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

  const resetImportState = () => {
    setImportStep("source");
    setImportRows([]);
    setImportSourceName(null);
    setSelectedFile(null);
    setPasteContent("");
    setHasHeaders(true);
    setMapping({ full_name: null, department: null, email: null, phone: null });
    setImportMode("skip_duplicates");
    setImportError(null);
    setImportResult(null);
  };

  const handleOpenImport = () => {
    resetImportState();
    setIsImportOpen(true);
  };

  const handleCloseImport = () => {
    setIsImportOpen(false);
  };

  const handleParseSource = async () => {
    setImportError(null);
    setImportResult(null);
    let rows: string[][] = [];
    try {
      if (selectedFile) {
        rows = await parseImportFile(selectedFile);
        setImportSourceName(selectedFile.name);
      } else if (pasteContent.trim()) {
        rows = parseDelimitedText(pasteContent);
        setImportSourceName("Presse-papiers");
      } else {
        setImportError("Ajoutez un fichier ou collez des données.");
        return;
      }
    } catch (parseError) {
      setImportError(parseError instanceof Error ? parseError.message : "Impossible de lire les données.");
      return;
    }
    if (!rows.length) {
      setImportError("Aucune ligne détectée.");
      return;
    }
    setImportRows(rows);
    setHasHeaders(true);
    setImportStep("preview");
  };

  const handleContinueFromPreview = () => {
    setImportError(null);
    if (isTemplateMatch) {
      setMapping({ full_name: 0, department: 1, email: 2, phone: 3 });
      setImportStep("validate");
      return;
    }
    setImportStep("mapping");
  };

  const handleContinueFromMapping = () => {
    setImportError(null);
    if (mapping.full_name === null) {
      setImportError("Le champ Nom complet doit être mappé.");
      return;
    }
    setImportStep("validate");
  };

  const handleImport = async () => {
    setImportError(null);
    if (!importSummary.validRows.length) {
      setImportError("Aucune ligne valide à importer.");
      return;
    }
    const payload: BulkImportPayload = {
      mode: importMode,
      rows: importSummary.validRows
    };
    await bulkImportCollaborators.mutateAsync(payload);
  };

  const handleExportCsv = () => {
    const rows = collaborators.map((collaborator) => [
      collaborator.full_name,
      collaborator.department ?? "",
      collaborator.email ?? "",
      collaborator.phone ?? ""
    ]);
    const csv = buildCsvContent([TEMPLATE_HEADERS, ...rows]);
    downloadFile(csv, "collaborateurs-export.csv");
  };

  const handleDownloadTemplate = () => {
    const csv = buildCsvContent([TEMPLATE_HEADERS, ...TEMPLATE_EXAMPLE_ROWS]);
    downloadFile(csv, "modele-collaborateurs.csv");
  };

  const defaultLayouts = useMemo<EditableLayoutSet>(
    () => ({
      lg: [
        { i: "collaborators-table", x: 0, y: 0, w: 8, h: 14 },
        { i: "collaborators-form", x: 8, y: 0, w: 4, h: 14 }
      ],
      md: [
        { i: "collaborators-table", x: 0, y: 0, w: 6, h: 14 },
        { i: "collaborators-form", x: 0, y: 14, w: 6, h: 12 }
      ],
      sm: [
        { i: "collaborators-table", x: 0, y: 0, w: 1, h: 14 },
        { i: "collaborators-form", x: 0, y: 14, w: 1, h: 12 }
      ]
    }),
    []
  );

  const blocks = useMemo<EditablePageBlock[]>(() => {
    const tableBlock: EditablePageBlock = {
      id: "collaborators-table",
      title: "Liste des collaborateurs",
      permission: { module: "dotations", action: "view" },
      render: () => (
        <div>
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
      )
    };

    const layoutBlocks: EditablePageBlock[] = [tableBlock];

    if (canEdit) {
      layoutBlocks.push({
        id: "collaborators-form",
        title: "Fiche collaborateur",
        permission: { module: "dotations", action: "edit" },
        render: () => (
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
        )
      });
    }

    return layoutBlocks;
  }, [
    canEdit,
    collaborators,
    createCollaborator.isPending,
    deleteCollaborator,
    formMode,
    formValues,
    handleSubmit,
    isFetching,
    selected,
    updateCollaborator.isPending
  ]);

  return (
    <>
      <EditablePageLayout
        pageId="module:clothing:collaborators"
        blocks={blocks}
        defaultLayouts={defaultLayouts}
        pagePermission={{ module: "dotations", action: "view" }}
        renderHeader={({ editButton, actionButtons, isEditing }) => (
          <div className="space-y-4">
            <header className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <h2 className="text-2xl font-semibold text-white">Collaborateurs</h2>
                <p className="text-sm text-slate-400">Liste des collaborateurs éligibles aux dotations.</p>
              </div>
              <div className="flex flex-wrap gap-2">
                {canEdit ? (
                  <button
                    type="button"
                    onClick={handleOpenImport}
                    className="rounded-md bg-slate-800 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-slate-700"
                    title="Importer une liste de collaborateurs"
                  >
                    Importer
                  </button>
                ) : null}
                <button
                  type="button"
                  onClick={handleExportCsv}
                  className="rounded-md bg-slate-800 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-slate-700"
                  title="Exporter les collaborateurs au format CSV"
                >
                  Exporter CSV
                </button>
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
                {editButton}
                {isEditing ? actionButtons : null}
              </div>
            </header>
            {message ? <p className="text-sm text-emerald-300">{message}</p> : null}
            {error ? <p className="text-sm text-red-400">{error}</p> : null}
          </div>
        )}
      />

      {isImportOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 px-3 py-4 sm:px-4 md:px-6">
          <div className="flex max-h-[calc(100vh-2rem)] w-full max-w-[1100px] flex-col rounded-lg border border-slate-800 bg-slate-900 text-slate-100 shadow-xl">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 px-4 py-4 sm:px-6">
              <div>
                <h3 className="text-lg font-semibold text-white">Importer des collaborateurs</h3>
                <p className="text-xs text-slate-400">
                  Étape {IMPORT_STEPS.indexOf(importStep) + 1} / {IMPORT_STEPS.length}
                </p>
              </div>
              <button
                type="button"
                onClick={handleCloseImport}
                className="rounded-md bg-slate-800 px-3 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-700"
              >
                Fermer
              </button>
            </div>

            <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4 sm:px-6">
              {importError ? <p className="text-sm text-red-300">{importError}</p> : null}

              {importStep === "source" ? (
                <div className="space-y-6">
                  <div
                    className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-slate-700 bg-slate-950/40 p-6 text-sm text-slate-300"
                    onDragOver={(event) => event.preventDefault()}
                    onDrop={(event) => {
                      event.preventDefault();
                      const file = event.dataTransfer.files?.[0];
                      if (file) {
                        setSelectedFile(file);
                      }
                    }}
                  >
                    <p className="font-semibold text-slate-100">Glissez-déposez un fichier CSV ou XLSX ici</p>
                    <p className="text-xs text-slate-400">Délimiteurs détectés automatiquement : ; , ou tabulations.</p>
                    {selectedFile ? (
                      <p className="text-xs text-emerald-300">Fichier sélectionné : {selectedFile.name}</p>
                    ) : null}
                  </div>

                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => fileInputRef.current?.click()}
                      className="rounded-md bg-indigo-500 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-400"
                    >
                      Choisir un fichier
                    </button>
                    <button
                      type="button"
                      onClick={() => pasteRef.current?.focus()}
                      className="rounded-md bg-slate-800 px-4 py-2 text-xs font-semibold text-slate-100 hover:bg-slate-700"
                    >
                      Coller depuis Google Sheets / Excel
                    </button>
                    <button
                      type="button"
                      onClick={handleDownloadTemplate}
                      className="rounded-md bg-slate-800 px-4 py-2 text-xs font-semibold text-slate-100 hover:bg-slate-700"
                    >
                      Télécharger un modèle CSV
                    </button>
                  </div>

                  <div className="space-y-2">
                    <p className="text-sm text-slate-200">
                      Depuis Google Sheets / Excel : sélectionnez les cellules → Ctrl+C → collez ici
                    </p>
                    <textarea
                      ref={pasteRef}
                      value={pasteContent}
                      onChange={(event) => setPasteContent(event.target.value)}
                      className="min-h-[140px] w-full rounded-md border border-slate-800 bg-slate-950 p-3 text-sm text-slate-100 focus:border-indigo-400 focus:outline-none"
                      placeholder="Collez votre tableau ici (tabulations ou CSV)."
                    />
                    <p className="text-xs text-slate-400">
                      Ce fichier peut être ouvert dans Excel ou importé dans Google Sheets.
                    </p>
                  </div>

                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".csv,.xlsx"
                    className="hidden"
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (file) {
                        setSelectedFile(file);
                      }
                    }}
                  />

                  <div className="flex justify-end border-t border-slate-800 pt-4">
                    <button
                      type="button"
                      onClick={handleParseSource}
                      className="rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-400"
                    >
                      Continuer
                    </button>
                  </div>
                </div>
              ) : null}

              {importStep === "preview" ? (
                <div className="space-y-4">
                  <div className="flex flex-wrap items-start justify-between gap-3 text-sm">
                    <div>
                      <p className="text-slate-200">
                        Source : <span className="font-semibold text-white">{importSourceName ?? "Import"}</span>
                      </p>
                      <p className="text-xs text-slate-400">
                        {importDataRows.length} ligne(s) détectée(s), {importHeaders.length} colonne(s).
                      </p>
                    </div>
                    <label className="flex items-center gap-2 text-xs text-slate-200">
                      <input
                        type="checkbox"
                        checked={hasHeaders}
                        onChange={(event) => setHasHeaders(event.target.checked)}
                        className="h-4 w-4 accent-indigo-500"
                      />
                      La première ligne contient les en-têtes
                    </label>
                  </div>

                  <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-slate-300">
                    <p>
                      Affichage :{" "}
                      <span className="font-semibold text-white">
                        {Math.min(50, filteredImportRows.length)}
                      </span>{" "}
                      / {filteredImportRows.length} lignes · total {importDataRows.length}
                    </p>
                    <input
                      value={previewFilter}
                      onChange={(event) => setPreviewFilter(event.target.value)}
                      placeholder="Rechercher dans l'aperçu"
                      className="w-full max-w-xs rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 focus:border-indigo-400 focus:outline-none"
                    />
                  </div>

                  <div className="min-w-0 overflow-hidden rounded-lg border border-slate-800">
                    <div className="max-h-[calc(100vh-24rem)] overflow-auto">
                      <table className="w-full table-fixed divide-y divide-slate-800 text-sm">
                        <thead className="bg-slate-950/80 text-slate-300">
                          <tr>
                            {importHeaders.map((header, index) => (
                              <th key={index} className="sticky top-0 px-3 py-2 text-left font-semibold">
                                {header}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-900">
                          {filteredImportRows.slice(0, 50).map((row, rowIndex) => (
                            <tr key={rowIndex} className="text-slate-100">
                              {importHeaders.map((header, colIndex) => (
                                <td
                                  key={colIndex}
                                  className={clsx(
                                    "px-3 py-2 text-slate-200",
                                    isPhoneColumn(header) ? "whitespace-nowrap" : "break-words"
                                  )}
                                  title={row[colIndex] ?? ""}
                                >
                                  {row[colIndex] ?? ""}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  {isTemplateMatch ? (
                    <p className="text-xs text-emerald-300">
                      Les en-têtes correspondent au modèle : le mapping sera ignoré.
                    </p>
                  ) : null}

                  <div className="flex justify-between border-t border-slate-800 pt-4">
                    <button
                      type="button"
                      onClick={() => setImportStep("source")}
                      className="rounded-md bg-slate-800 px-3 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-700"
                    >
                      Retour
                    </button>
                    <button
                      type="button"
                      onClick={handleContinueFromPreview}
                      className="rounded-md bg-indigo-500 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-400"
                    >
                      Continuer
                    </button>
                  </div>
                </div>
              ) : null}

              {importStep === "mapping" ? (
                <div className="space-y-4">
                  <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]">
                    <div className="order-2 min-w-0 space-y-3 lg:order-1">
                      <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-slate-300">
                        <p>
                          Aperçu :{" "}
                          <span className="font-semibold text-white">
                            {Math.min(50, filteredImportRows.length)}
                          </span>{" "}
                          / {filteredImportRows.length} lignes
                        </p>
                        <input
                          value={previewFilter}
                          onChange={(event) => setPreviewFilter(event.target.value)}
                          placeholder="Rechercher dans l'aperçu"
                          className="w-full max-w-xs rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 focus:border-indigo-400 focus:outline-none"
                        />
                      </div>
                      <div className="min-w-0 overflow-hidden rounded-lg border border-slate-800">
                        <div className="max-h-[calc(100vh-24rem)] overflow-auto">
                          <table className="w-full table-fixed divide-y divide-slate-800 text-sm">
                            <thead className="bg-slate-950/80 text-slate-300">
                              <tr>
                                {importHeaders.map((header, index) => (
                                  <th key={index} className="sticky top-0 px-3 py-2 text-left font-semibold">
                                    {header}
                                  </th>
                                ))}
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-900">
                              {filteredImportRows.slice(0, 50).map((row, rowIndex) => (
                                <tr key={rowIndex} className="text-slate-100">
                                  {importHeaders.map((header, colIndex) => (
                                    <td
                                      key={colIndex}
                                      className={clsx(
                                        "px-3 py-2 text-slate-200",
                                        isPhoneColumn(header) ? "whitespace-nowrap" : "break-words"
                                      )}
                                      title={row[colIndex] ?? ""}
                                    >
                                      {row[colIndex] ?? ""}
                                    </td>
                                  ))}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    </div>
                    <div className="order-1 space-y-4 rounded-lg border border-slate-800 bg-slate-950/40 p-4 lg:order-2">
                      <p className="text-sm text-slate-200">
                        Associez les colonnes détectées aux champs collaborateurs.
                      </p>
                      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-1">
                        <MappingSelect
                          label="Nom complet (obligatoire)"
                          value={mapping.full_name}
                          onChange={(value) => setMapping((prev) => ({ ...prev, full_name: value }))}
                          options={importHeaders}
                          required
                        />
                        <MappingSelect
                          label="Service"
                          value={mapping.department}
                          onChange={(value) => setMapping((prev) => ({ ...prev, department: value }))}
                          options={importHeaders}
                        />
                        <MappingSelect
                          label="Email"
                          value={mapping.email}
                          onChange={(value) => setMapping((prev) => ({ ...prev, email: value }))}
                          options={importHeaders}
                        />
                        <MappingSelect
                          label="Téléphone"
                          value={mapping.phone}
                          onChange={(value) => setMapping((prev) => ({ ...prev, phone: value }))}
                          options={importHeaders}
                        />
                      </div>
                    </div>
                  </div>
                  <div className="flex justify-between border-t border-slate-800 pt-4">
                    <button
                      type="button"
                      onClick={() => setImportStep("preview")}
                      className="rounded-md bg-slate-800 px-3 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-700"
                    >
                      Retour
                    </button>
                    <button
                      type="button"
                      onClick={handleContinueFromMapping}
                      className="rounded-md bg-indigo-500 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-400"
                    >
                      Continuer
                    </button>
                  </div>
                </div>
              ) : null}

              {importStep === "validate" ? (
                <div className="space-y-5">
                  <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-4 text-sm">
                    <p className="text-slate-200">
                      {importSummary.totalRows} ligne(s) analysée(s) ·{" "}
                      <span className="font-semibold text-white">{importSummary.validRows.length}</span> valide(s)
                    </p>
                    <p className="text-xs text-slate-400">
                      Doublons internes : {importSummary.duplicateCount} · Erreurs : {importSummary.errorCount}
                    </p>
                  </div>

                  <div className="space-y-2">
                    <p className="text-sm font-semibold text-white">Mode d'import</p>
                    <label className="flex items-center gap-2 text-xs text-slate-200">
                      <input
                        type="radio"
                        checked={importMode === "skip_duplicates"}
                        onChange={() => setImportMode("skip_duplicates")}
                        className="h-4 w-4 accent-indigo-500"
                      />
                      Ignorer les doublons
                    </label>
                    <label className="flex items-center gap-2 text-xs text-slate-200">
                      <input
                        type="radio"
                        checked={importMode === "upsert"}
                        onChange={() => setImportMode("upsert")}
                        className="h-4 w-4 accent-indigo-500"
                      />
                      Mettre à jour si email déjà existant (upsert)
                    </label>
                  </div>

                  {importSummary.errors.length ? (
                    <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-4 text-xs text-slate-200">
                      <p className="text-sm font-semibold text-white">Erreurs détectées</p>
                      <ul className="mt-2 space-y-1">
                        {importSummary.errors.slice(0, 5).map((err) => (
                          <li key={`${err.rowIndex}-${err.message}`}>
                            Ligne {err.rowIndex} : {err.message}
                          </li>
                        ))}
                      </ul>
                      {importSummary.errors.length > 5 ? (
                        <p className="mt-2 text-xs text-slate-400">
                          + {importSummary.errors.length - 5} autre(s) erreur(s)
                        </p>
                      ) : null}
                    </div>
                  ) : null}

                  {importResult ? (
                    <div className="rounded-lg border border-emerald-500/40 bg-emerald-900/10 p-4 text-xs text-emerald-100">
                      <p className="font-semibold text-emerald-200">Résultat de l'import</p>
                      <p>
                        {importResult.created} créé(s), {importResult.updated} mis à jour,{" "}
                        {importResult.skipped} ignoré(s)
                      </p>
                      {importResult.errors.length ? (
                        <ul className="mt-2 list-disc pl-4">
                          {importResult.errors.slice(0, 5).map((err) => (
                            <li key={`${err.rowIndex}-${err.message}`}>
                              Ligne {err.rowIndex} : {err.message}
                            </li>
                          ))}
                        </ul>
                      ) : null}
                    </div>
                  ) : null}

                  <div className="flex flex-wrap justify-between gap-2 border-t border-slate-800 pt-4">
                    <button
                      type="button"
                      onClick={() => setImportStep(isTemplateMatch ? "preview" : "mapping")}
                      className="rounded-md bg-slate-800 px-3 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-700"
                    >
                      Retour
                    </button>
                    <button
                      type="button"
                      onClick={handleImport}
                      disabled={bulkImportCollaborators.isPending}
                      className="rounded-md bg-indigo-500 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-70"
                    >
                      {bulkImportCollaborators.isPending
                        ? "Import en cours..."
                        : `Importer ${importSummary.validRows.length} collaborateurs`}
                    </button>
                  </div>
                </div>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}

const IMPORT_STEPS: ImportStep[] = ["source", "preview", "mapping", "validate"];

const TEMPLATE_HEADERS = ["Nom complet", "Service", "Email", "Téléphone"];

const TEMPLATE_EXAMPLE_ROWS = [
  ["Marie Dubois", "Logistique", "marie.dubois@example.com", "+33612345678"],
  ["Julien Martin", "Achats", "julien.martin@example.com", "0612345678"],
  ["Sofia Petit", "Opérations", "", ""]
];

const HEADER_HEURISTICS: Record<keyof MappingState, string[]> = {
  full_name: ["nom", "nom complet", "name", "fullname", "collaborateur", "agent"],
  department: ["service", "site", "departement", "département", "department", "team"],
  email: ["email", "e-mail", "mail", "adresse mail"],
  phone: ["telephone", "téléphone", "tel", "mobile", "phone"]
};

const EMAIL_REGEX = /^[^@\s]+@[^@\s]+\.[^@\s]+$/i;

const isPhoneColumn = (header: string) => header.toLowerCase().includes("tel");

function MappingSelect({
  label,
  value,
  onChange,
  options,
  required = false
}: {
  label: string;
  value: number | null;
  onChange: (value: number | null) => void;
  options: string[];
  required?: boolean;
}) {
  return (
    <label className="space-y-2 text-xs text-slate-300">
      <span className="block text-sm font-semibold text-slate-100">{label}</span>
      <select
        className="w-full rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none"
        value={value ?? ""}
        onChange={(event) => {
          const newValue = event.target.value === "" ? null : Number(event.target.value);
          onChange(Number.isNaN(newValue) ? null : newValue);
        }}
      >
        {!required ? <option value="">Ne pas importer</option> : null}
        {options.map((option, index) => (
          <option key={`${option}-${index}`} value={index}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

function deriveHeaders(rows: string[][], hasHeaders: boolean): string[] {
  if (!rows.length) {
    return [];
  }
  if (hasHeaders) {
    return rows[0].map((header, index) => header || `Colonne ${index + 1}`);
  }
  const maxColumns = rows.reduce((max, row) => Math.max(max, row.length), 0);
  return Array.from({ length: maxColumns }, (_, index) => `Colonne ${index + 1}`);
}

function headersMatchTemplate(headers: string[]): boolean {
  if (headers.length !== TEMPLATE_HEADERS.length) {
    return false;
  }
  return headers.every((header, index) => header.trim() === TEMPLATE_HEADERS[index]);
}

function buildAutoMapping(headers: string[]): MappingState {
  const normalizedHeaders = headers.map((header) => normalizeHeader(header));
  const mapping: MappingState = {
    full_name: null,
    department: null,
    email: null,
    phone: null
  };
  (Object.keys(HEADER_HEURISTICS) as Array<keyof MappingState>).forEach((key) => {
    const candidates = HEADER_HEURISTICS[key].map((value) => normalizeHeader(value));
    const foundIndex = normalizedHeaders.findIndex((header) => candidates.includes(header));
    if (foundIndex >= 0) {
      mapping[key] = foundIndex;
    }
  });
  return mapping;
}

function normalizeHeader(value: string): string {
  return value
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function normalizeWhitespace(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }
  const normalized = value.replace(/\s+/g, " ").trim();
  return normalized.length ? normalized : null;
}

function normalizeEmail(value: string | null | undefined): string | null {
  const normalized = normalizeWhitespace(value);
  if (!normalized) {
    return null;
  }
  const lowered = normalized.toLowerCase();
  return EMAIL_REGEX.test(lowered) ? lowered : null;
}

function normalizePhone(value: string | null | undefined): string | null {
  const normalized = normalizeWhitespace(value);
  if (!normalized) {
    return null;
  }
  const keepPlus = normalized.startsWith("+");
  const digits = normalized.replace(/\D/g, "");
  if (!digits) {
    return null;
  }
  return keepPlus ? `+${digits}` : digits;
}

function summarizeImportRows(
  rows: string[][],
  mapping: MappingState,
  hasHeaders: boolean
): {
  validRows: BulkImportRow[];
  errors: BulkImportError[];
  duplicateCount: number;
  errorCount: number;
  totalRows: number;
} {
  const validRows: BulkImportRow[] = [];
  const errors: BulkImportError[] = [];
  const seenKeys = new Set<string>();
  let duplicateCount = 0;
  const totalRows = rows.length;

  rows.forEach((row, index) => {
    const rowIndex = hasHeaders ? index + 2 : index + 1;
    const fullName = normalizeWhitespace(mapping.full_name !== null ? row[mapping.full_name] : null);
    const department = normalizeWhitespace(mapping.department !== null ? row[mapping.department] : null);
    const email = normalizeEmail(mapping.email !== null ? row[mapping.email] : null);
    const phone = normalizePhone(mapping.phone !== null ? row[mapping.phone] : null);

    if (!fullName) {
      errors.push({ rowIndex, message: "Nom complet manquant" });
      return;
    }
    if (mapping.email !== null && row[mapping.email] && !email) {
      errors.push({ rowIndex, message: "Adresse email invalide" });
      return;
    }
    const dedupeKey = email ?? `${fullName.toLowerCase()}::${phone ?? ""}`;
    if (seenKeys.has(dedupeKey)) {
      duplicateCount += 1;
      return;
    }
    seenKeys.add(dedupeKey);
    validRows.push({
      full_name: fullName,
      department,
      email,
      phone
    });
  });

  return {
    validRows,
    errors,
    duplicateCount,
    errorCount: errors.length,
    totalRows
  };
}

function detectDelimiter(text: string): string {
  const sampleLines = text.split(/\r?\n/).slice(0, 10);
  const delimiters = [";", ",", "\t"];
  const scores = delimiters.map((delimiter) => {
    return sampleLines.reduce((count, line) => count + (line.split(delimiter).length - 1), 0);
  });
  const maxScore = Math.max(...scores);
  const index = scores.findIndex((score) => score === maxScore);
  return delimiters[index] ?? ";";
}

function parseDelimitedText(text: string, delimiter?: string): string[][] {
  const effectiveDelimiter = delimiter ?? detectDelimiter(text);
  const rows: string[][] = [];
  let current = "";
  let row: string[] = [];
  let inQuotes = false;
  const sanitizedText = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");

  for (let i = 0; i < sanitizedText.length; i += 1) {
    const char = sanitizedText[i];
    const nextChar = sanitizedText[i + 1];
    if (char === "\"") {
      if (inQuotes && nextChar === "\"") {
        current += "\"";
        i += 1;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (char === effectiveDelimiter && !inQuotes) {
      row.push(current);
      current = "";
    } else if (char === "\n" && !inQuotes) {
      row.push(current);
      rows.push(row);
      row = [];
      current = "";
    } else {
      current += char;
    }
  }

  if (current.length || row.length) {
    row.push(current);
    rows.push(row);
  }

  if (rows.length && rows[0].length) {
    rows[0][0] = rows[0][0].replace(/^\uFEFF/, "");
  }

  return rows.filter((line) => line.some((cell) => cell.trim() !== ""));
}

async function parseImportFile(file: File): Promise<string[][]> {
  if (file.name.toLowerCase().endsWith(".xlsx")) {
    let xlsxModule: typeof import("xlsx");
    try {
      xlsxModule = await loadXlsxModule();
    } catch (importError) {
      throw new Error(
        "Impossible de charger le module Excel. Réessayez ou utilisez un fichier CSV."
      );
    }
    const buffer = await file.arrayBuffer();
    const workbook = xlsxModule.read(buffer, { type: "array" });
    const sheetName = workbook.SheetNames[0];
    const sheet = workbook.Sheets[sheetName];
    if (!sheet) {
      return [];
    }
    const rows = xlsxModule.utils.sheet_to_json(sheet, { header: 1, raw: false }) as Array<Array<unknown>>;
    return rows.map((row) => row.map((cell) => (cell === null || cell === undefined ? "" : String(cell))));
  }
  const text = await file.text();
  return parseDelimitedText(text);
}

function escapeCsvValue(value: string): string {
  if (/[\";\n]/.test(value)) {
    return `"${value.replace(/\"/g, "\"\"")}"`;
  }
  return value;
}

function buildCsvContent(rows: string[][]): string {
  const content = rows.map((row) => row.map((value) => escapeCsvValue(value)).join(";")).join("\n");
  return `\uFEFF${content}`;
}

function downloadFile(content: string, filename: string) {
  const blob = new Blob([content], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
