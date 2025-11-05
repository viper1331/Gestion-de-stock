import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { useEffect, useMemo, useState } from "react";

import { useAuth } from "../features/auth/useAuth";
import { ThemeToggle } from "./ThemeToggle";
import { MicToggle } from "../features/voice/MicToggle";
import { useModulePermissions } from "../features/permissions/useModulePermissions";

export function AppLayout() {
  const { user, logout, initialize, isReady, isCheckingSession } = useAuth();
  const modulePermissions = useModulePermissions({ enabled: Boolean(user) });
  const navigate = useNavigate();

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
                  to: "/",
                  label: "Vue d'ensemble",
                  tooltip: "Consulter le tableau de bord habillement",
                  module: "clothing"
                },
                {
                  to: "/barcode",
                  label: "Codes-barres",
                  tooltip: "Générer et scanner les codes-barres d'habillement",
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
                if (!link.module) {
                  return true;
                }
                if (user.role === "admin") {
                  return true;
                }
                return modulePermissions.canAccess(link.module);
              })
            }))
            .filter((section) => section.links.length > 0)
        }))
        .filter((group) => group.sections.length > 0);
    },
    [modulePermissions.canAccess, user]
  );

  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({
    habillement: true,
    "inventaires-specialises": false,
    pharmacie: false,
    administration: false
  });

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
      <aside className="w-64 border-r border-slate-800 bg-slate-900 p-6">
        <Link to="/" className="block text-lg font-semibold" title="Revenir à l'accueil">
          Gestion Stock Pro
        </Link>
        <nav className="mt-8 flex flex-col gap-4 text-sm">
          {navigationGroups.map((group) => {
            const isOpen = openGroups[group.id] ?? false;

            return (
              <div key={group.id}>
                <button
                  type="button"
                  onClick={() => toggleGroup(group.id)}
                  className="flex w-full items-center justify-between rounded-md px-3 py-2 font-semibold text-slate-200 transition-colors hover:bg-slate-800"
                  aria-expanded={isOpen}
                  title={group.tooltip}
                >
                  <span>{group.label}</span>
                  <span aria-hidden>{isOpen ? "−" : "+"}</span>
                </button>
                {isOpen ? (
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
                              end={link.to === "/"}
                              className={({ isActive }) => navClass(isActive)}
                              title={link.tooltip}
                            >
                              {link.label}
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
        <div className="mt-auto flex flex-col gap-3 pt-6">
          <div className="rounded-md border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-300">
            <p className="font-semibold text-slate-200">{user.username}</p>
            <p>Rôle : {user.role}</p>
          </div>
          <MicToggle />
          <ThemeToggle />
          <button
            onClick={logout}
            className="rounded-md bg-red-500 px-3 py-2 text-sm font-semibold text-white shadow hover:bg-red-400"
            title="Se déconnecter de votre session"
          >
            Se déconnecter
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto bg-slate-950 p-6">
        <Outlet />
      </main>
    </div>
  );
}

function navClass(isActive: boolean) {
  return `rounded-md px-3 py-2 font-medium transition-colors ${
    isActive ? "bg-slate-800 text-white" : "text-slate-300 hover:bg-slate-800"
  }`;
}
