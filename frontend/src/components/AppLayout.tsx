import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { useEffect, useMemo, useState } from "react";

import { useAuth } from "../features/auth/useAuth";
import { ThemeToggle } from "./ThemeToggle";
import { MicToggle } from "../features/voice/MicToggle";
import { useModulePermissions } from "../features/permissions/useModulePermissions";
import { useUiStore } from "../app/store";

export function AppLayout() {
  const { user, logout, initialize, isReady, isCheckingSession } = useAuth();
  const modulePermissions = useModulePermissions({ enabled: Boolean(user) });
  const navigate = useNavigate();
  const { sidebarOpen, toggleSidebar } = useUiStore();

  useEffect(() => {
    initialize();
  }, [initialize]);

  useEffect(() => {
    if (isReady && !user) {
      navigate("/login", { replace: true });
    }
  }, [isReady, navigate, user]);

  const navigationGroups = useMemo(
    () => {
      type NavLinkItem = {
        to: string;
        label: string;
        tooltip: string;
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
        sections: NavSection[];
      };

      const groups: NavGroup[] = [
        {
          id: "code-barres",
          label: "Codes-barres",
          tooltip: "Accéder aux outils de codes-barres",
          sections: [
            {
              id: "code-barres-operations",
              label: "Opérations",
              tooltip: "Outils de gestion des codes-barres",
              links: [
                {
                  to: "/barcode",
                  label: "Codes-barres",
                  tooltip: "Générer et scanner les codes-barres",
                  module: "barcode"
                }
              ]
            }
          ]
        },
        {
          id: "habillement",
          label: "Habillement",
          tooltip: "Accéder aux fonctionnalités d'habillement",
          sections: [
            {
              id: "habillement-operations",
              label: "Opérations",
              tooltip: "Outils de suivi du stock d'habillement",
              links: [
                {
                  to: "/inventory",
                  label: "Inventaire habillement",
                  tooltip: "Consulter le tableau de bord habillement",
                  module: "clothing"
                },
                {
                  to: "/reports",
                  label: "Rapports",
                  tooltip: "Analyser les rapports d'habillement",
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
                  label: "Fournisseurs",
                  tooltip: "Gérer les fournisseurs d'habillement",
                  module: "suppliers"
                },
                {
                  to: "/collaborators",
                  label: "Collaborateurs",
                  tooltip: "Suivre les collaborateurs et leurs dotations",
                  module: "dotations"
                },
                {
                  to: "/dotations",
                  label: "Dotations",
                  tooltip: "Attribuer les dotations d'habillement",
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
          sections: [
            {
              id: "inventaires-dedies",
              label: "Inventaires dédiés",
              tooltip: "Inventaires dédiés aux véhicules et remises",
              links: [
                {
                  to: "/vehicle-inventory",
                  label: "Inventaire véhicules",
                  tooltip: "Gérer le parc véhicules",
                  module: "vehicle_inventory"
                },
                {
                  to: "/vehicle-inventory/qr-codes",
                  label: "QR véhicules",
                  tooltip: "Partager les fiches matériel via QR codes",
                  modules: ["vehicle_qrcodes", "vehicle_inventory"]
                },
                {
                  to: "/remise-inventory",
                  label: "Inventaire remises",
                  tooltip: "Suivre les stocks mis en remise",
                  module: "inventory_remise"
                }
              ]
            }
          ]
        },
        {
          id: "pharmacie",
          label: "Pharmacie",
          tooltip: "Accéder aux fonctionnalités de pharmacie",
          sections: [
            {
              id: "pharmacie-operations",
              label: "Opérations",
              tooltip: "Outils de suivi du stock de pharmacie",
              links: [
                {
                  to: "/pharmacy",
                  label: "Vue d'ensemble pharmacie",
                  tooltip: "Consulter le tableau de bord pharmacie",
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
                }
              ]
            }
          ]
        },
        {
          id: "administration",
          label: "Administration",
          tooltip: "Paramétrer votre environnement",
          sections: [
            {
              id: "administration-parametres",
              label: "Configuration",
              tooltip: "Paramètres et gestion des accès",
              links: [
                {
                  to: "/settings",
                  label: "Paramètres",
                  tooltip: "Configurer les paramètres généraux"
                },
                {
                  to: "/users",
                  label: "Utilisateurs",
                  tooltip: "Administrer les comptes utilisateurs",
                  adminOnly: true
                },
                {
                  to: "/permissions",
                  label: "Permissions",
                  tooltip: "Gérer les droits d'accès",
                  adminOnly: true
                },
                {
                  to: "/updates",
                  label: "Mises à jour",
                  tooltip: "Gérer les mises à jour GitHub du serveur",
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
    [modulePermissions.canAccess, user]
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
    setOpenGroups((prev) => ({
      ...prev,
      [groupId]: !prev[groupId]
    }));
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
          <Link to="/" className="block text-lg font-semibold" title="Revenir à l'accueil">
            <span aria-hidden>{sidebarOpen ? "Gestion Stock Pro" : "GSP"}</span>
            <span className="sr-only">Gestion Stock Pro</span>
          </Link>
          <button
            type="button"
            onClick={toggleSidebar}
            className="rounded-md border border-slate-800 bg-slate-900 p-2 text-slate-200 shadow hover:bg-slate-800"
            aria-label={sidebarOpen ? "Réduire le menu principal" : "Déplier le menu principal"}
          >
            <span aria-hidden>{sidebarOpen ? "⟨" : "⟩"}</span>
          </button>
        </div>
        <nav className={`mt-8 flex flex-col gap-4 text-sm ${sidebarOpen ? "" : "items-center"}`}>
          <NavLink
            to="/"
            end
            className={({ isActive }) => navClass(isActive, sidebarOpen)}
            title="Accéder à la page d'accueil personnalisée"
          >
            <span aria-hidden>{sidebarOpen ? "Accueil" : "A"}</span>
            <span className="sr-only">Accueil</span>
          </NavLink>
          {navigationGroups.map((group) => {
            const isOpen = openGroups[group.id] ?? false;

            return (
              <div key={group.id}>
                <button
                  type="button"
                  onClick={() => toggleGroup(group.id)}
                  className={`flex w-full items-center rounded-md font-semibold text-slate-200 transition-colors hover:bg-slate-800 ${
                    sidebarOpen ? "justify-between px-3 py-2" : "justify-center p-2"
                  }`}
                  aria-expanded={isOpen}
                  title={group.tooltip}
                >
                  <span>
                    <span aria-hidden>{sidebarOpen ? group.label : group.label.charAt(0)}</span>
                    <span className="sr-only">{group.label}</span>
                  </span>
                  {sidebarOpen ? <span aria-hidden>{isOpen ? "−" : "+"}</span> : null}
                </button>
                {sidebarOpen && isOpen ? (
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
                              <span aria-hidden>{sidebarOpen ? link.label : link.label.charAt(0)}</span>
                              <span className="sr-only">{link.label}</span>
                            </NavLink>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            );
          })}
        </nav>
        {modulePermissions.isLoading && user?.role !== "admin" ? (
          <p className="mt-3 text-xs text-slate-500">Chargement des modules autorisés...</p>
        ) : null}
        <div className="mt-auto flex w-full flex-col gap-3 pt-6">
          <div
            className={`rounded-md border border-slate-800 bg-slate-900 text-xs text-slate-300 ${
              sidebarOpen ? "px-3 py-2" : "px-2 py-1 text-center"
            }`}
          >
            <p className="font-semibold text-slate-200" aria-hidden={!sidebarOpen}>
              {sidebarOpen ? user.username : user.username.charAt(0)}
            </p>
            <p className={sidebarOpen ? undefined : "sr-only"}>Rôle : {user.role}</p>
            {!sidebarOpen ? <span className="sr-only">Rôle : {user.role}</span> : null}
          </div>
          <MicToggle />
          <ThemeToggle />
          <button
            onClick={logout}
            className={`rounded-md bg-red-500 text-sm font-semibold text-white shadow hover:bg-red-400 ${
              sidebarOpen ? "px-3 py-2" : "px-2 py-1 text-center"
            }`}
            title="Se déconnecter de votre session"
          >
            <span aria-hidden>{sidebarOpen ? "Se déconnecter" : "✕"}</span>
            <span className="sr-only">Se déconnecter</span>
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
  return `rounded-md font-medium transition-colors ${
    expanded ? "px-3 py-2" : "px-2 py-1 justify-center"
  } ${isActive ? "bg-slate-800 text-white" : "text-slate-300 hover:bg-slate-800"}`;
}
