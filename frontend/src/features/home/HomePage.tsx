import { useMemo } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { useAuth } from "../auth/useAuth";
import {
  fetchConfigEntries,
  fetchUserHomepageConfig
} from "../../lib/config";
import { api } from "../../lib/api";
import { buildHomeConfig } from "./homepageConfig";
import { useModulePermissions } from "../permissions/useModulePermissions";
import { fetchUpdateAvailability, fetchUpdateStatus } from "../updates/api";

const DEFAULT_PHARMACY_LOW_STOCK_THRESHOLD = 5;

const PATH_MODULE_MAP: Record<string, string> = {
  "/barcode": "barcode",
  "/inventory": "clothing",
  "/reports": "clothing",
  "/purchase-orders": "clothing",
  "/suppliers": "suppliers",
  "/collaborators": "dotations",
  "/dotations": "dotations",
  "/vehicle-inventory": "vehicle_inventory",
  "/remise-inventory": "inventory_remise",
  "/pharmacy": "pharmacy"
};

function normalizeInternalPath(path: string): string | null {
  if (!path) {
    return null;
  }

  const trimmed = path.trim();
  if (trimmed.length === 0) {
    return null;
  }

  const base = typeof window !== "undefined" ? window.location.origin : "http://localhost";

  try {
    const url = new URL(trimmed, base);
    const normalized = url.pathname.replace(/\/+/g, "/");
    const withoutTrailingSlash = normalized.replace(/\/$/, "");
    return withoutTrailingSlash.length > 0 ? withoutTrailingSlash : "/";
  } catch {
    if (!trimmed.startsWith("/")) {
      return null;
    }
    const sanitized = trimmed.split(/[?#]/)[0];
    const normalized = sanitized.replace(/\/+/g, "/");
    const withoutTrailingSlash = normalized.replace(/\/$/, "");
    return withoutTrailingSlash.length > 0 ? withoutTrailingSlash : "/";
  }
}

interface LowStockReport {
  item: {
    id: number;
    name: string;
    quantity: number;
    low_stock_threshold: number;
  };
  shortage: number;
}

interface PharmacyItem {
  id: number;
  name: string;
  quantity: number;
  low_stock_threshold: number | null;
}

export function HomePage() {
  const { user } = useAuth();
  const { canAccess, isLoading: isModuleLoading } = useModulePermissions({ enabled: Boolean(user) });
  const isAdmin = user?.role === "admin";
  const { data: entries = [], isFetching: isFetchingGlobal } = useQuery({
    queryKey: ["config", "global"],
    queryFn: fetchConfigEntries
  });
  const { data: personalEntries = [], isFetching: isFetchingPersonal } = useQuery({
    queryKey: ["config", "homepage", "personal"],
    queryFn: fetchUserHomepageConfig
  });

  const canSeeClothingAlerts = useMemo(() => {
    if (!user) {
      return false;
    }

    if (user.role === "admin") {
      return true;
    }

    if (isModuleLoading) {
      return false;
    }

    return canAccess("clothing");
  }, [canAccess, isModuleLoading, user]);

  const canSeePharmacyAlerts = useMemo(() => {
    if (!user) {
      return false;
    }

    if (user.role === "admin") {
      return true;
    }

    if (isModuleLoading) {
      return false;
    }

    return canAccess("pharmacy");
  }, [canAccess, isModuleLoading, user]);

  const {
    data: clothingLowStock = [],
    isFetching: isFetchingClothingAlerts
  } = useQuery({
    queryKey: ["home", "low-stock", "clothing"],
    queryFn: async () => {
      const response = await api.get<LowStockReport[]>("/reports/low-stock");
      return response.data;
    },
    enabled: canSeeClothingAlerts
  });

  const {
    data: pharmacyItems = [],
    isFetching: isFetchingPharmacyAlerts
  } = useQuery({
    queryKey: ["home", "low-stock", "pharmacy"],
    queryFn: async () => {
      const response = await api.get<PharmacyItem[]>("/pharmacy/");
      return response.data;
    },
    enabled: canSeePharmacyAlerts
  });

  const {
    data: updateStatus,
    isFetching: isFetchingUpdates,
    isError: isUpdateStatusError,
    error: updateStatusError
  } = useQuery({
    queryKey: ["updates", "status"],
    queryFn: fetchUpdateStatus,
    enabled: Boolean(user) && isAdmin
  });

  const {
    data: updateAvailability,
    isFetching: isFetchingAvailability,
    isError: isUpdateAvailabilityError,
    error: updateAvailabilityError
  } = useQuery({
    queryKey: ["updates", "availability"],
    queryFn: fetchUpdateAvailability,
    enabled: Boolean(user) && !isAdmin
  });

  const config = useMemo(
    () => buildHomeConfig([...entries, ...personalEntries]),
    [entries, personalEntries]
  );

  const quickLinks = useMemo(
    () =>
      [
        { label: config.primary_link_label, path: config.primary_link_path },
        { label: config.secondary_link_label, path: config.secondary_link_path }
      ].filter((link) => link.path.trim().length > 0),
    [config.primary_link_label, config.primary_link_path, config.secondary_link_label, config.secondary_link_path]
  );

  const accessibleQuickLinks = useMemo(() => {
    if (!user) {
      return [];
    }

    if (user.role === "admin") {
      return quickLinks;
    }

    if (isModuleLoading) {
      return [];
    }

    return quickLinks.filter((link) => {
      const normalizedPath = normalizeInternalPath(link.path);
      if (!normalizedPath) {
        return false;
      }

      const moduleId = PATH_MODULE_MAP[normalizedPath];
      if (!moduleId) {
        return true;
      }

      return canAccess(moduleId);
    });
  }, [canAccess, isModuleLoading, quickLinks, user]);

  const focusCards = [
    { label: config.focus_1_label, description: config.focus_1_description },
    { label: config.focus_2_label, description: config.focus_2_description },
    { label: config.focus_3_label, description: config.focus_3_description }
  ];

  const pharmacyLowStock = useMemo(() => {
    if (!canSeePharmacyAlerts) {
      return [] as PharmacyItem[];
    }

    return pharmacyItems.filter((item) => {
      const threshold = item.low_stock_threshold ?? DEFAULT_PHARMACY_LOW_STOCK_THRESHOLD;
      if (threshold <= 0) {
        return false;
      }
      return item.quantity <= threshold;
    });
  }, [canSeePharmacyAlerts, pharmacyItems]);

  const lowStockCards = useMemo(
    () => {
      const cards: {
        key: string;
        title: string;
        description: string;
        link: string;
        items: { id: number; name: string; quantity: number; threshold: number; shortage: number }[];
        isLoading: boolean;
      }[] = [];

      if (canSeeClothingAlerts) {
        cards.push({
          key: "clothing",
          title: "Habillement",
          description: "Articles en dessous du seuil dans l'inventaire habillement.",
          link: "/inventory",
          items: clothingLowStock.map((entry) => ({
            id: entry.item.id,
            name: entry.item.name,
            quantity: entry.item.quantity,
            threshold: entry.item.low_stock_threshold,
            shortage: entry.shortage
          })),
          isLoading: isFetchingClothingAlerts
        });
      }

      if (canSeePharmacyAlerts) {
        cards.push({
          key: "pharmacy",
          title: "Pharmacie",
          description: "Médicaments sous le seuil de sécurité.",
          link: "/pharmacy",
          items: pharmacyLowStock.map((item) => ({
            id: item.id,
            name: item.name,
            quantity: item.quantity,
            threshold: item.low_stock_threshold ?? DEFAULT_PHARMACY_LOW_STOCK_THRESHOLD,
            shortage: Math.max((item.low_stock_threshold ?? DEFAULT_PHARMACY_LOW_STOCK_THRESHOLD) - item.quantity, 0)
          })),
          isLoading: isFetchingPharmacyAlerts
        });
      }

      return cards;
    },
    [
      canSeeClothingAlerts,
      canSeePharmacyAlerts,
      clothingLowStock,
      isFetchingClothingAlerts,
      isFetchingPharmacyAlerts,
      pharmacyLowStock
    ]
  );

  const isCheckingUpdates = isAdmin ? isFetchingUpdates : isFetchingAvailability;

  const updateStatusErrorMessage = useMemo(() => {
    const hasError = isAdmin ? isUpdateStatusError : isUpdateAvailabilityError;
    if (!hasError) {
      return null;
    }
    const rawError = isAdmin ? updateStatusError : updateAvailabilityError;
    if (rawError instanceof Error) {
      return rawError.message;
    }
    return "Impossible de récupérer l'état des mises à jour.";
  }, [isAdmin, isUpdateAvailabilityError, isUpdateStatusError, updateAvailabilityError, updateStatusError]);

  const hasPendingUpdate = isAdmin
    ? Boolean(updateStatus?.pending_update)
    : Boolean(updateAvailability?.pending_update);

  const trackedBranch = isAdmin ? updateStatus?.branch ?? null : updateAvailability?.branch ?? null;

  return (
    <section className="space-y-6">
      <div className="rounded-xl border border-slate-800 bg-gradient-to-r from-indigo-500/10 via-slate-950 to-slate-950 p-6 shadow-lg">
        <p className="text-sm text-indigo-300">Bonjour {user?.username ?? ""} !</p>
        <h1 className="mt-2 text-3xl font-bold text-white sm:text-4xl">{config.title}</h1>
        <p className="mt-3 max-w-3xl text-sm text-slate-300 sm:text-base">{config.subtitle}</p>
        <p className="mt-4 max-w-3xl text-sm text-slate-400">{config.welcome_message}</p>
        {isModuleLoading && user?.role !== "admin" ? (
          <p className="mt-4 text-xs text-slate-500">Chargement des liens disponibles selon vos autorisations...</p>
        ) : null}
        {accessibleQuickLinks.length > 0 ? (
          <div className="mt-6 flex flex-wrap gap-3">
            {accessibleQuickLinks.map((link) => (
              <Link
                key={`${link.label}-${link.path}`}
                to={link.path}
                className="inline-flex items-center justify-center rounded-md bg-indigo-500 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-indigo-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-300"
              >
                {link.label}
              </Link>
            ))}
          </div>
        ) : null}
        {!isModuleLoading && accessibleQuickLinks.length === 0 && quickLinks.length > 0 ? (
          <p className="mt-4 text-xs text-slate-500">
            Aucun raccourci n'est disponible avec vos droits actuels. Contactez un administrateur pour accéder aux modules
            correspondants.
          </p>
        ) : null}
        {isFetchingGlobal || isFetchingPersonal ? (
          <p className="mt-4 text-xs text-slate-500">Mise à jour de la configuration...</p>
        ) : null}
      </div>

      {config.announcement ? (
        <div className="rounded-lg border border-indigo-500/40 bg-indigo-950/60 p-4 text-indigo-100 shadow">
          <p className="text-xs font-semibold uppercase tracking-wide text-indigo-300">Annonce</p>
          <p className="mt-2 text-sm leading-relaxed">{config.announcement}</p>
        </div>
      ) : null}

      {user ? (
        <section className="rounded-lg border border-slate-800 bg-slate-900/70 p-4 shadow-sm">
          <header className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="text-base font-semibold text-white">Alertes stock bas</h2>
              <p className="text-xs text-slate-400">Modules surveillés selon vos autorisations.</p>
            </div>
            {isModuleLoading && user.role !== "admin" ? (
              <span className="text-xs text-slate-500">Analyse des permissions en cours...</span>
            ) : null}
          </header>
          {lowStockCards.length === 0 && !(isModuleLoading && user.role !== "admin") ? (
            <p className="mt-3 text-sm text-slate-400">
              Aucun module de stock accessible avec vos droits actuels.
            </p>
          ) : null}
          {lowStockCards.length > 0 ? (
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              {lowStockCards.map((card) => (
                <article
                  key={card.key}
                  className="space-y-3 rounded-lg border border-slate-800 bg-slate-950/60 p-4 shadow-sm"
                >
                  <div className="flex items-center justify-between gap-2">
                    <div>
                      <h3 className="text-base font-semibold text-white">{card.title}</h3>
                      <p className="text-xs text-slate-400">{card.description}</p>
                    </div>
                    <Link
                      to={card.link}
                      className="inline-flex items-center justify-center rounded-md border border-indigo-500 px-3 py-1.5 text-xs font-semibold text-indigo-200 hover:bg-indigo-500/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-300"
                    >
                      Ouvrir le module
                    </Link>
                  </div>
                  {card.isLoading ? (
                    <p className="text-sm text-slate-400">Chargement des alertes...</p>
                  ) : card.items.length > 0 ? (
                    <>
                      <ul className="space-y-2">
                        {card.items.slice(0, 4).map((item) => (
                          <li
                            key={`${card.key}-${item.id}`}
                            className="rounded-md border border-slate-800 bg-slate-900/70 px-3 py-2"
                          >
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-semibold text-white">{item.name}</span>
                              <span className="text-amber-300">Manque : {item.shortage}</span>
                            </div>
                            <p className="text-xs text-slate-400">
                              Stock : {item.quantity} / Seuil : {item.threshold}
                            </p>
                          </li>
                        ))}
                      </ul>
                      {card.items.length > 4 ? (
                        <p className="text-xs text-slate-400">
                          +{card.items.length - 4} article(s) supplémentaires sous le seuil.
                        </p>
                      ) : null}
                    </>
                  ) : (
                    <p className="text-sm text-emerald-300">Aucune alerte pour ce module.</p>
                  )}
                </article>
              ))}
            </div>
          ) : null}
        </section>
      ) : null}

      <section className="rounded-lg border border-slate-800 bg-slate-900/70 p-4 shadow-sm">
        <header className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-base font-semibold text-white">Mises à jour du serveur</h2>
            <p className="text-xs text-slate-400">Gardez l'application synchronisée avec GitHub.</p>
          </div>
          {isAdmin ? (
            <Link
              to="/updates"
              className="inline-flex items-center justify-center rounded-md border border-indigo-500 px-3 py-1.5 text-xs font-semibold text-indigo-200 hover:bg-indigo-500/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-300"
            >
              Gérer les mises à jour
            </Link>
          ) : null}
        </header>
        {isAdmin ? (
          <div className="mt-3 space-y-2 text-sm">
            {isCheckingUpdates ? (
              <p className="text-slate-400">Vérification des mises à jour en cours...</p>
            ) : updateStatusErrorMessage ? (
              <p className="text-red-300">{updateStatusErrorMessage}</p>
            ) : hasPendingUpdate ? (
              <p className="text-amber-300">
                Une mise à jour GitHub est disponible. Appliquez-la depuis la page « Mises à jour ».
              </p>
            ) : (
              <p className="text-emerald-300">Aucune mise à jour en attente. Le serveur est synchronisé avec la branche suivie.</p>
            )}
            {trackedBranch ? (
              <p className="text-xs text-slate-400">Branche suivie : {trackedBranch}</p>
            ) : null}
            {updateStatus?.latest_pull_request ? (
              <p className="text-xs text-slate-500">
                Dernière PR fusionnée : {updateStatus.latest_pull_request.title} (#{updateStatus.latest_pull_request.number}).
              </p>
            ) : null}
          </div>
        ) : (
          <div className="mt-3 space-y-2 text-sm">
            {isCheckingUpdates ? (
              <p className="text-slate-400">Vérification des mises à jour en cours...</p>
            ) : updateStatusErrorMessage ? (
              <p className="text-red-300">{updateStatusErrorMessage}</p>
            ) : hasPendingUpdate ? (
              <p className="text-amber-300">
                Une mise à jour est disponible. Prévenez un administrateur afin qu'il l'applique lors de sa prochaine connexion.
              </p>
            ) : (
              <p className="text-slate-300">Aucune mise à jour en attente pour le moment.</p>
            )}
            {trackedBranch ? (
              <p className="text-xs text-slate-500">Branche suivie : {trackedBranch}</p>
            ) : null}
          </div>
        )}
      </section>

      <section className="space-y-3">
        <header>
          <h2 className="text-lg font-semibold text-white">Vos priorités</h2>
          <p className="text-sm text-slate-400">
            Adaptez ces encadrés depuis les paramètres pour refléter l'organisation de votre service.
          </p>
        </header>
        <div className="grid gap-4 md:grid-cols-3">
          {focusCards.map((card) => (
            <article
              key={card.label}
              className="rounded-lg border border-slate-800 bg-slate-900/70 p-4 shadow-sm transition-colors hover:border-indigo-500/60"
            >
              <h3 className="text-base font-semibold text-white">{card.label}</h3>
              <p className="mt-2 text-sm text-slate-400">{card.description}</p>
            </article>
          ))}
        </div>
      </section>

      {user?.role === "admin" ? (
        <section className="rounded-lg border border-slate-800 bg-slate-900 p-4 shadow">
          <h2 className="text-base font-semibold text-white">Personnalisez l'accueil</h2>
          <p className="mt-2 text-sm text-slate-400">
            Les textes et liens de cette page proviennent de la section « homepage » de la configuration. Modifiez-les pour
            refléter vos procédures internes.
          </p>
          <div className="mt-4">
            <Link
              to="/settings"
              className="inline-flex items-center justify-center rounded-md border border-indigo-500 px-3 py-2 text-sm font-semibold text-indigo-200 hover:bg-indigo-500/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-300"
            >
              Ouvrir les paramètres
            </Link>
          </div>
        </section>
      ) : null}
    </section>
  );
}
