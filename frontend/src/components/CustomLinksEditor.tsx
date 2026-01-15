import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";

import { api } from "../lib/api";
import { AppTextInput } from "./AppTextInput";

type LinkModule = "vehicle_qr" | "pharmacy";

interface LinkCategory {
  id: number;
  module: LinkModule;
  key: string;
  label: string;
  placeholder: string | null;
  help_text: string | null;
  is_required: boolean;
  sort_order: number;
  is_active: boolean;
}

interface LinkValue {
  category_key: string;
  url: string;
}

interface CustomLinksEditorProps {
  module: LinkModule;
  itemId: string;
  readonly?: boolean;
}

const isValidUrl = (value: string) => {
  if (!value.trim()) return true;
  try {
    const parsed = new URL(value);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
};

const getLinksEndpoint = (module: LinkModule, itemId: string) => {
  if (module === "vehicle_qr") {
    return `/vehicle-qr/items/${itemId}/links`;
  }
  return `/pharmacy/items/${itemId}/links`;
};

export function CustomLinksEditor({ module, itemId, readonly = false }: CustomLinksEditorProps) {
  const queryClient = useQueryClient();
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [status, setStatus] = useState<string | null>(null);

  const { data: categories = [], isLoading: isLoadingCategories } = useQuery({
    queryKey: ["link-categories", module],
    queryFn: async () => {
      const response = await api.get<LinkCategory[]>("/link-categories", {
        params: { module }
      });
      return response.data;
    }
  });

  const { data: linkValues = [], isLoading: isLoadingLinks } = useQuery({
    queryKey: ["item-links", module, itemId],
    queryFn: async () => {
      const response = await api.get<LinkValue[]>(getLinksEndpoint(module, itemId));
      return response.data;
    },
    enabled: Boolean(itemId)
  });

  const activeCategories = useMemo(() => {
    return [...categories]
      .filter((category) => category.is_active)
      .sort((a, b) => {
        if (a.sort_order !== b.sort_order) {
          return a.sort_order - b.sort_order;
        }
        return a.label.localeCompare(b.label, "fr");
      });
  }, [categories]);

  useEffect(() => {
    if (!activeCategories.length) {
      setDrafts({});
      return;
    }
    const linkMap = new Map(linkValues.map((entry) => [entry.category_key, entry.url ?? ""]));
    const next: Record<string, string> = {};
    activeCategories.forEach((category) => {
      next[category.key] = linkMap.get(category.key) ?? "";
    });
    setDrafts(next);
  }, [activeCategories, linkValues, itemId]);

  const errors = useMemo(() => {
    const next: Record<string, string> = {};
    activeCategories.forEach((category) => {
      const value = drafts[category.key] ?? "";
      if (category.is_required && !value.trim()) {
        next[category.key] = "Lien requis";
        return;
      }
      if (!isValidUrl(value)) {
        next[category.key] = "URL invalide (HTTP/HTTPS)";
      }
    });
    return next;
  }, [activeCategories, drafts]);

  const hasErrors = Object.keys(errors).length > 0;

  const saveLinks = useMutation({
    mutationFn: async () => {
      const payload = {
        links: activeCategories.map((category) => ({
          category_key: category.key,
          url: drafts[category.key] ?? ""
        }))
      };
      await api.put(getLinksEndpoint(module, itemId), payload);
    },
    onSuccess: async () => {
      setStatus("Liens enregistrés avec succès.");
      await queryClient.invalidateQueries({ queryKey: ["item-links", module, itemId] });
    },
    onError: (error) => {
      let message = "Impossible d'enregistrer les liens.";
      if (isAxiosError(error)) {
        const detail = error.response?.data?.detail;
        if (typeof detail === "string" && detail.trim().length > 0) {
          message = detail;
        }
      }
      setStatus(message);
    }
  });

  const handleChange = (key: string, value: string) => {
    setDrafts((previous) => ({
      ...previous,
      [key]: value
    }));
  };

  const isLoading = isLoadingCategories || isLoadingLinks;

  if (isLoading) {
    return <p className="text-sm text-slate-500 dark:text-slate-400">Chargement des liens...</p>;
  }

  if (!activeCategories.length) {
    return (
      <p className="text-sm text-slate-500 dark:text-slate-400">
        Aucune catégorie de lien active n'est disponible pour ce module.
      </p>
    );
  }

  return (
    <div className="flex min-w-0 flex-col gap-4">
      {activeCategories.map((category) => (
        <label key={category.id} className="text-sm font-semibold text-slate-700 dark:text-slate-200">
          <span className="flex items-center gap-2">
            {category.label}
            {category.is_required && (
              <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold uppercase text-amber-700">
                Requis
              </span>
            )}
          </span>
          <AppTextInput
            type="url"
            value={drafts[category.key] ?? ""}
            onChange={(event) => handleChange(category.key, event.target.value)}
            placeholder={category.placeholder ?? "https://..."}
            disabled={readonly}
            className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none disabled:cursor-not-allowed disabled:bg-slate-100 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:disabled:bg-slate-900"
          />
          {category.help_text && (
            <p className="mt-1 text-xs font-normal text-slate-500 dark:text-slate-400">
              {category.help_text}
            </p>
          )}
          {errors[category.key] && (
            <p className="mt-1 text-xs font-normal text-rose-500">{errors[category.key]}</p>
          )}
        </label>
      ))}

      <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500 dark:text-slate-400">
        <button
          type="button"
          onClick={() => saveLinks.mutate()}
          disabled={readonly || saveLinks.isPending || hasErrors}
          className="inline-flex items-center gap-2 rounded-md bg-indigo-500 px-3 py-2 text-xs font-semibold text-white shadow hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {saveLinks.isPending ? "Enregistrement..." : "Enregistrer les liens"}
        </button>
        {status && <span>{status}</span>}
      </div>
    </div>
  );
}
