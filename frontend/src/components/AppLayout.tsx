import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { useAuth } from "../features/auth/useAuth";
import { ThemeToggle } from "./ThemeToggle";
import { MicToggle } from "../features/voice/MicToggle";
import { useModulePermissions } from "../features/permissions/useModulePermissions";
import { useUiStore } from "../app/store";
import { fetchConfigEntries } from "../lib/config";
import { buildModuleTitleMap } from "../lib/moduleTitles";
import { useDebugFlags } from "../lib/debug";

export function AppLayout() {
  const { user, logout, initialize, isReady, isCheckingSession } = useAuth();
  const modulePermissions = useModulePermissions({ enabled: Boolean(user) });
  const navigate = useNavigate();
  const { sidebarOpen, toggleSidebar } = useUiStore();
  const debugFlags = useDebugFlags();

  const { data: configEntries = [] } = useQuery({
    queryKey: ["config", "global"],
    queryFn: fetchConfigEntries,
    enabled: Boolean(user)
  });

  const moduleTitles = useMemo(() => buildModuleTitleMap(configEntries), [configEntries]);

  const isDebugActive =
    debugFlags.frontend_debug ||
    debugFlags.backend_debug ||
    debugFlags.inventory_debug ||
    debugFlags.network_debug;

  const inactivityCooldownMs = useMemo(() => {
    const cooldownEntry = configEntries.find(
      (entry) => entry.section === "general" && entry.key === "inactivity_timeout_minutes"
    );
    if (!cooldownEntry) {
      return null;
    }
    const minutes = Number.parseInt(cooldownEntry.value, 10);
    if (!Number.isFinite(minutes) || minutes <= 0) {
      return null;
    }
    return minutes * 60_000;
  }, [configEntries]);

  useEffect(() => {
    initialize();
  }, [initialize]);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, []);

  useEffect(() => {
    if (isReady && !user) {
      navigate("/login", { replace: true });
    }
  }, [isReady, navigate, user]);

  useEffect(() => {
    if (!user || !inactivityCooldownMs) {
      return undefined;
    }

    let timeoutId: number | undefined;
    const resetTimer = () => {
      if (timeoutId) {
        window.clearTimeout(timeoutId);
      }
      timeoutId = window.setTimeout(() => {
        logout();
      }, inactivityCooldownMs);
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        resetTimer();
      }
    };

    const activityEvents = ["mousemove", "keydown", "mousedown", "touchstart", "scroll", "focus"];
    activityEvents.forEach((eventName) => window.addEventListener(eventName, resetTimer));
    document.addEventListener("visibilitychange", handleVisibilityChange);
    resetTimer();

    return () => {
      if (timeoutId) {
        window.clearTimeout(timeoutId);
      }
      activityEvents.forEach((eventName) => window.removeEventListener(eventName, resetTimer));
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [inactivityCooldownMs, logout, user]);

  const navigationGroups = useMemo(
    () => {
      type NavLinkItem = {
        to: string;
        label: string;
        tooltip: string;
        icon?: string;
        module?: string;
        modules?: string[];
        adminOnly?: boolean;
      };

      type NavSection = {
        id: string;
        label: string;
        tooltip: string;
        links: NavLinkItem[];
      };

      type NavGroup = {
        id: string;
        label: string;
        tooltip: string;
        icon?: string;
        sections: NavSection[];
      };

      const groups: NavGroup[] = [
        {
          id: "code-barres",
          label: moduleTitles.barcode,
          tooltip: "Accéder aux outils de codes-barres",
          icon: "🏷️",
          sections: [
            {
              id: "code-barres-operations",
              label: "Opérations",
              tooltip: "Outils de gestion des codes-barres",
              links: [
                {
                  to: "/barcode",
                  label: moduleTitles.barcode,
                  tooltip: "Générer et scanner les codes-barres",
                  icon: "📌",
                  module: "barcode"
                }
              ]
            }
          ]
        },
        {
          id: "habillement",
          label: moduleTitles.clothing,
          tooltip: "Accéder aux fonctionnalités d'habillement",
          icon: "🧥",
          sections: [
            {
              id: "habillement-operations",
              label: "Opérations",
              tooltip: "Outils de suivi du stock d'habillement",
              links: [
                {
                  to: "/inventory",
                  label: moduleTitles.clothing,
                  tooltip: "Consulter le tableau de bord habillement",
                  icon: "📦",
                  module: "clothing"
                },
                {
                  to: "/reports",
                  label: "Rapports",
                  tooltip: "Analyser les rapports d'habillement",
                  icon: "📈",
                  module: "clothing"
                }
              ]
            },
            {
              id: "habillement-purchase-orders",
              label: "Bons de commande",
              tooltip: "Créer et suivre les bons de commande",
              links: [
                {
                  to: "/purchase-orders",
                  label: "Bons de commande",
                  tooltip: "Gérer les bons de commande d'habillement",
                  icon: "🧾",
                  module: "clothing"
                }
              ]
            },
            {
              id: "habillement-ressources",
              label: "Ressources",
              tooltip: "Référentiels liés à l'habillement",
              links: [
                {
                  to: "/suppliers",
                  label: moduleTitles.suppliers,
                  tooltip: "Gérer les fournisseurs d'habillement",
                  icon: "🏭",
                  module: "suppliers"
                },
                {
                  to: "/collaborators",
                  label: "Collaborateurs",
                  tooltip: "Suivre les collaborateurs et leurs dotations",
                  icon: "👥",
                  module: "dotations"
                },
                {
                  to: "/dotations",
                  label: moduleTitles.dotations,
                  tooltip: "Attribuer les dotations d'habillement",
                  icon: "🎯",
                  module: "dotations"
                }
              ]
            }
          ]
        },
        {
          id: "inventaires-specialises",
          label: "Inventaires spécialisés",
          tooltip: "Accéder aux inventaires véhicules et remises",
          icon: "🚚",
          sections: [
            {
              id: "inventaires-dedies",
              label: "Inventaires dédiés",
              tooltip: "Inventaires dédiés aux véhicules et remises",
              links: [
                {
                  to: "/vehicle-inventory",
                  label: moduleTitles.vehicle_inventory,
                  tooltip: "Gérer le parc véhicules",
                  icon: "🚗",
                  module: "vehicle_inventory"
                },
                {
                  to: "/vehicle-inventory/qr-codes",
                  label: moduleTitles.vehicle_qrcodes,
                  tooltip: "Partager les fiches matériel via QR codes",
                  icon: "🔖",
                  modules: ["vehicle_qrcodes", "vehicle_inventory"]
                },
                {
                  to: "/remise-inventory",
                  label: moduleTitles.inventory_remise,
                  tooltip: "Suivre les stocks mis en remise",
                  icon: "🏢",
                  module: "inventory_remise"
                }
              ]
            }
          ]
        },
        {
          id: "pharmacie",
          label: moduleTitles.pharmacy,
          tooltip: "Accéder aux fonctionnalités de pharmacie",
          icon: "💊",
          sections: [
            {
              id: "pharmacie-operations",
              label: "Opérations",
              tooltip: "Outils de suivi du stock de pharmacie",
              links: [
                {
                  to: "/pharmacy",
                  label: moduleTitles.pharmacy,
                  tooltip: "Consulter le tableau de bord pharmacie",
                  icon: "🏥",
                  module: "pharmacy"
                }
              ]
            }
          ]
        },
        {
          id: "support",
          label: "Support",
          tooltip: "Consulter les informations du programme",
          icon: "ℹ️",
          sections: [
            {
              id: "support-ressources",
              label: "Ressources",
              tooltip: "Informations légales et version logicielle",
              links: [
                {
                  to: "/about",
                  label: "À propos",
                  tooltip: "Consulter la licence et la version en ligne",
                  icon: "📘",
                }
              ]
            }
          ]
        },
        {
          id: "administration",
          label: "Administration",
          tooltip: "Paramétrer votre environnement",
          icon: "🛠️",
          sections: [
            {
              id: "administration-parametres",
              label: "Configuration",
              tooltip: "Paramètres et gestion des accès",
              links: [
                {
                  to: "/settings",
                  label: "Paramètres",
                  tooltip: "Configurer les paramètres généraux",
                  icon: "⚙️",
                },
                {
                  to: "/system-config",
                  label: "Configuration système",
                  tooltip: "Ajuster les URLs publiques et les origines autorisées",
                  icon: "🌐",
                  adminOnly: true
                },
                {
                  to: "/users",
                  label: "Utilisateurs",
                  tooltip: "Administrer les comptes utilisateurs",
                  icon: "👤",
                  adminOnly: true
                },
                {
                  to: "/permissions",
                  label: "Permissions",
                  tooltip: "Gérer les droits d'accès",
                  icon: "🔒",
                  adminOnly: true
                },
                {
                  to: "/updates",
                  label: "Mises à jour",
                  tooltip: "Gérer les mises à jour GitHub du serveur",
                  icon: "⬆️",
                  adminOnly: true
                }
              ]
            }
          ]
        }
      ];

      if (!user) {
        return [];
      }

      return groups
        .map((group) => ({
          ...group,
          sections: group.sections
            .map((section) => ({
              ...section,
              links: section.links.filter((link) => {
                if (link.adminOnly) {
                  return user?.role === "admin";
                }
                const allowedModules = link.modules ?? (link.module ? [link.module] : []);
                if (allowedModules.length === 0) {
                  return true;
                }
                if (user.role === "admin") {
                  return true;
                }
                return allowedModules.some((module) => modulePermissions.canAccess(module));
              })
            }))
            .filter((section) => section.links.length > 0)
        }))
        .filter((group) => group.sections.length > 0);
    },
    [modulePermissions.canAccess, moduleTitles, user]
  );

  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(navigationGroups.map((group) => [group.id, false]))
  );

  useEffect(() => {
    setOpenGroups((prev) => {
      const next: Record<string, boolean> = {};
      let hasChanges = false;
      const groupIds = new Set(navigationGroups.map((group) => group.id));

      navigationGroups.forEach((group) => {
        const previousValue = prev[group.id] ?? false;
        next[group.id] = previousValue;
        if (prev[group.id] === undefined) {
          hasChanges = true;
        }
      });

      Object.keys(prev).forEach((key) => {
        if (!groupIds.has(key)) {
          hasChanges = true;
        }
      });

      if (!hasChanges) {
        return prev;
      }

      return next;
    });
  }, [navigationGroups]);

  const toggleGroup = (groupId: string) => {
    setOpenGroups((prev) => {
      const isCurrentlyOpen = prev[groupId] ?? false;
      const next: Record<string, boolean> = {};

      Object.keys(prev).forEach((key) => {
        next[key] = false;
      });

      if (!isCurrentlyOpen) {
        next[groupId] = true;
      }

      return next;
    });
  };

  if (!isReady || isCheckingSession) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950 text-slate-100">
        <p className="text-sm text-slate-300">Chargement de votre session...</p>
      </div>
    );
  }

  if (!user) {
    return null;
  }

  return (
    <div className="flex h-screen bg-slate-950 text-slate-50">
      <aside
        className={`relative flex h-full flex-col border-r border-slate-800 bg-slate-900 transition-all duration-200 ${
          sidebarOpen ? "w-64 p-6" : "w-20 p-4"
        }`}
      >
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Link to="/" className="block text-lg font-semibold" title="Revenir à l'accueil">
              <span aria-hidden>{sidebarOpen ? "Gestion Stock Pro" : "GSP"}</span>
              <span className="sr-only">Gestion Stock Pro</span>
            </Link>
            {isDebugActive ? (
              <span className="rounded bg-red-600 px-2 py-1 text-[10px] font-bold uppercase tracking-wide text-white">
                DEBUG
              </span>
            ) : null}
          </div>
          <button
            type="button"
            onClick={toggleSidebar}
            className="rounded-md border border-slate-800 bg-slate-900 p-2 text-slate-200 shadow hover:bg-slate-800"
            aria-label={sidebarOpen ? "Réduire le menu principal" : "Déplier le menu principal"}
          >
            <span aria-hidden>{sidebarOpen ? "⟨" : "⟩"}</span>
          </button>
        </div>
        <div
          className={`mt-8 flex min-h-0 flex-1 flex-col ${
            sidebarOpen ? "overflow-hidden" : "overflow-visible"
          }`}
        >
          <nav
            className={`flex min-h-0 flex-1 flex-col gap-3 text-sm ${
              sidebarOpen ? "overflow-y-auto pr-2" : "overflow-visible items-center"
            }`}
          >
            <NavLink
              to="/"
              end
              className={({ isActive }) => navClass(isActive, sidebarOpen)}
              title="Accéder à la page d'accueil personnalisée"
          >
            <NavIcon symbol="🏠" label="Accueil" />
            <span className={sidebarOpen ? "block" : "sr-only"}>Accueil</span>
          </NavLink>
            {navigationGroups.map((group) => {
              const isOpen = openGroups[group.id] ?? false;

              return (
                <div key={group.id} className="relative w-full">
                  <button
                    type="button"
                    onClick={() => toggleGroup(group.id)}
                    className={`group flex w-full items-center rounded-md font-semibold text-slate-200 transition-colors hover:bg-slate-800 ${
                      sidebarOpen ? "justify-between px-3 py-2" : "h-11 justify-center"
                    }`}
                    aria-expanded={isOpen}
                    title={group.tooltip}
                  >
                    <span className="flex items-center gap-3">
                      <NavIcon symbol={group.icon} label={group.label} />
                      <span className={sidebarOpen ? "block text-left" : "sr-only"}>{group.label}</span>
                    </span>
                    {sidebarOpen ? <span aria-hidden>{isOpen ? "−" : "+"}</span> : null}
                  </button>
                  {isOpen ? (
                    sidebarOpen ? (
                      <div className="mt-3 space-y-4 border-l border-slate-800 pl-3">
                        {group.sections.map((section) => (
                          <div key={section.id}>
                            <p
                              className="text-xs font-semibold uppercase tracking-wide text-slate-500"
                              title={section.tooltip}
                            >
                              {section.label}
                            </p>
                            <div className="mt-2 flex flex-col gap-1">
                              {section.links.map((link) => (
                                <NavLink
                                  key={link.to}
                                  to={link.to}
                                  end={link.to === "/" || link.to === "/inventory"}
                                  className={({ isActive }) => navClass(isActive, sidebarOpen)}
                                  title={link.tooltip}
                                >
                                  <NavIcon symbol={link.icon} label={link.label} />
                                  <span>{link.label}</span>
                                </NavLink>
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="absolute left-full top-0 z-20 ml-3 w-64 space-y-4 rounded-lg border border-slate-800 bg-slate-900 p-3 text-left shadow-2xl">
                        {group.sections.map((section) => (
                          <div key={section.id}>
                            <p
                              className="text-xs font-semibold uppercase tracking-wide text-slate-500"
                              title={section.tooltip}
                            >
                              {section.label}
                            </p>
                            <div className="mt-2 flex flex-col gap-1">
                              {section.links.map((link) => (
                                <NavLink
                                  key={link.to}
                                  to={link.to}
                                  end={link.to === "/" || link.to === "/inventory"}
                                  className={({ isActive }) => navClass(isActive, true)}
                                  title={link.tooltip}
                                  onClick={() => toggleGroup(group.id)}
                                >
                                  <NavIcon symbol={link.icon} label={link.label} />
                                  <span>{link.label}</span>
                                </NavLink>
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    )
                  ) : null}
                </div>
              );
            })}
          </nav>
          {modulePermissions.isLoading && user?.role !== "admin" ? (
            <p className="mt-3 text-xs text-slate-500">Chargement des modules autorisés...</p>
          ) : null}
        </div>
        <div className="mt-auto flex w-full flex-col gap-3 pt-6">
          <div
            className={`flex items-center gap-2 rounded-md border border-slate-800 bg-slate-900 text-xs text-slate-300 ${
              sidebarOpen ? "px-3 py-2" : "px-2 py-1 justify-center"
            }`}
          >
            <NavIcon symbol={user.username.charAt(0).toUpperCase()} label={user.username} />
            <div className={sidebarOpen ? "leading-tight" : "sr-only"}>
              <p className="font-semibold text-slate-200">{user.username}</p>
              <p>Rôle : {user.role}</p>
            </div>
            {!sidebarOpen ? <span className="sr-only">Rôle : {user.role}</span> : null}
          </div>
          <MicToggle compact={!sidebarOpen} />
          <ThemeToggle compact={!sidebarOpen} />
          <button
            onClick={logout}
            className={`flex items-center justify-center gap-2 rounded-md bg-red-500 text-sm font-semibold text-white shadow hover:bg-red-400 ${
              sidebarOpen ? "px-3 py-2" : "px-2 py-2"
            }`}
            title="Se déconnecter de votre session"
          >
            <span aria-hidden>⎋</span>
            <span className={sidebarOpen ? "block" : "sr-only"}>Se déconnecter</span>
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto bg-slate-950 p-6">
        <Outlet />
      </main>
    </div>
  );
}

function navClass(isActive: boolean, expanded: boolean) {
  return `flex items-center gap-3 rounded-md font-medium transition-colors ${
    expanded ? "px-3 py-2" : "h-11 w-full justify-center"
  } ${isActive ? "bg-slate-800 text-white shadow-sm" : "text-slate-300 hover:bg-slate-800"}`;
}

function NavIcon({ symbol, label }: { symbol?: string; label: string }) {
  return (
    <span
      aria-hidden
      className="flex h-9 w-9 items-center justify-center rounded-full border border-slate-800 bg-slate-800/60 text-lg"
    >
      {symbol ?? label.charAt(0)}
    </span>
  );
}
