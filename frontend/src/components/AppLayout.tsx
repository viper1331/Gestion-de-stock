import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useEffect, useMemo, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  DndContext,
  DragEndEvent,
  MouseSensor,
  TouchSensor,
  closestCenter,
  useSensor,
  useSensors
} from "@dnd-kit/core";
import { SortableContext, arrayMove, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

import { shallow } from "zustand/shallow";

import { useAuth } from "../features/auth/useAuth";
import { ThemeToggle } from "./ThemeToggle";
import { MicToggle } from "../features/voice/MicToggle";
import { useModulePermissions } from "../features/permissions/useModulePermissions";
import { useUiStore } from "../app/store";
import { fetchConfigEntries } from "../lib/config";
import { fetchSiteContext } from "../lib/sites";
import { buildModuleTitleMap } from "../lib/moduleTitles";
import { isDebugEnabled } from "../lib/debug";
import { applyOrder, loadMenuOrder, saveMenuOrder } from "../lib/menuOrder";

type MenuItem =
  | {
      id: string;
      type: "link";
      label: string;
      tooltip: string;
      icon?: string;
      to: string;
      isPinned?: boolean;
    }
  | {
      id: string;
      type: "group";
      label: string;
      tooltip: string;
      icon?: string;
      group: {
        id: string;
        label: string;
        tooltip: string;
        icon?: string;
        sections: {
          id: string;
          label: string;
          tooltip: string;
          links: {
            to: string;
            label: string;
            tooltip: string;
            icon?: string;
          }[];
        }[];
      };
      isPinned?: boolean;
    };

export function AppLayout() {
  const { user, logout, initialize, isReady, isCheckingSession } = useAuth();
  const modulePermissions = useModulePermissions({ enabled: Boolean(user) });
  const navigate = useNavigate();
  const location = useLocation();
  const { sidebarOpen, toggleSidebar } = useUiStore(
    (state) => ({
      sidebarOpen: state.sidebarOpen,
      toggleSidebar: state.toggleSidebar
    }),
    shallow
  );
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(() =>
    typeof window === "undefined" ? false : window.matchMedia("(max-width: 640px)").matches
  );
  const [isDesktop, setIsDesktop] = useState(() =>
    typeof window === "undefined" ? true : window.matchMedia("(min-width: 768px)").matches
  );
  const drawerRef = useRef<HTMLDivElement | null>(null);

  const { data: configEntries = [] } = useQuery({
    queryKey: ["config", "global"],
    queryFn: fetchConfigEntries,
    enabled: Boolean(user)
  });
  const { data: siteContext } = useQuery({
    queryKey: ["site-context", user?.username],
    queryFn: fetchSiteContext,
    enabled: user?.role === "admin"
  });

  const moduleTitles = useMemo(() => buildModuleTitleMap(configEntries), [configEntries]);

  const isDebugActive =
    isDebugEnabled("frontend_debug") ||
    isDebugEnabled("backend_debug") ||
    isDebugEnabled("inventory_debug") ||
    isDebugEnabled("network_debug");

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
    if (typeof window === "undefined") {
      return undefined;
    }
    const mediaQuery = window.matchMedia("(min-width: 768px)");
    const mobileQuery = window.matchMedia("(max-width: 640px)");
    const handleChange = (event: MediaQueryListEvent) => {
      setIsDesktop(event.matches);
    };
    const handleMobileChange = (event: MediaQueryListEvent) => {
      setIsMobile(event.matches);
    };
    setIsDesktop(mediaQuery.matches);
    setIsMobile(mobileQuery.matches);
    mediaQuery.addEventListener("change", handleChange);
    mobileQuery.addEventListener("change", handleMobileChange);
    return () => {
      mediaQuery.removeEventListener("change", handleChange);
      mobileQuery.removeEventListener("change", handleMobileChange);
    };
  }, []);

  useEffect(() => {
    if (isDesktop) {
      setMobileDrawerOpen(false);
    }
  }, [isDesktop]);

  useEffect(() => {
    if (!isMobile) {
      setMobileDrawerOpen(false);
    }
  }, [isMobile]);

  useEffect(() => {
    setMobileDrawerOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!mobileDrawerOpen || !isMobile) {
      return undefined;
    }
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [mobileDrawerOpen, isMobile]);

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

  useEffect(() => {
    if (!mobileDrawerOpen) {
      return undefined;
    }
    const drawer = drawerRef.current;
    const focusableSelector =
      "a[href],button:not([disabled]),textarea,input,select,[tabindex]:not([tabindex='-1'])";
    const focusable = drawer ? Array.from(drawer.querySelectorAll<HTMLElement>(focusableSelector)) : [];
    const first = focusable[0];
    const last = focusable[focusable.length - 1];

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMobileDrawerOpen(false);
        return;
      }
      if (event.key !== "Tab" || focusable.length === 0) {
        return;
      }
      const activeElement = document.activeElement;
      if (event.shiftKey) {
        if (activeElement === first || activeElement === drawer) {
          event.preventDefault();
          last?.focus();
        }
      } else if (activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    requestAnimationFrame(() => {
      first?.focus();
    });

    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [mobileDrawerOpen]);

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
          id: "operations",
          label: "Opérations",
          tooltip: "Accéder aux opérations terrain",
          icon: "🛠️",
          sections: [
            {
              id: "operations-links",
              label: "Liens personnalisés",
              tooltip: "Gérer les liens partagés par module",
              links: [
                {
                  to: "/operations/vehicle-qr",
                  label: "QR codes véhicules",
                  tooltip: "Gérer les liens et QR codes véhicules",
                  icon: "🔖",
                  modules: ["vehicle_qrcodes", "vehicle_inventory"]
                },
                {
                  to: "/operations/pharmacy-links",
                  label: "Liens Pharmacie",
                  tooltip: "Gérer les liens associés aux articles pharmacie",
                  icon: "💊",
                  module: "pharmacy"
                },
                {
                  to: "/operations/link-categories",
                  label: "Configuration liens",
                  tooltip: "Configurer les catégories de liens",
                  icon: "⚙️",
                  adminOnly: true
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
          id: "communication",
          label: "Communication",
          tooltip: "Échanger des messages internes",
          icon: "💬",
          sections: [
            {
              id: "communication-messages",
              label: "Messagerie",
              tooltip: "Consulter et envoyer des messages internes",
              links: [
                {
                  to: "/messages",
                  label: "Messagerie",
                  tooltip: "Ouvrir la messagerie interne",
                  icon: "✉️"
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
                  to: "/admin-settings",
                  label: "Paramètres avancés",
                  tooltip: "Configurer les types de véhicules et champs personnalisés",
                  icon: "🧩",
                  adminOnly: true
                },
                {
                  to: "/system-config",
                  label: "Configuration système",
                  tooltip: "Ajuster les URLs publiques et les origines autorisées",
                  icon: "🌐",
                  adminOnly: true
                },
                {
                  to: "/pdf-config",
                  label: "Configuration PDF",
                  tooltip: "Personnaliser les exports PDF",
                  icon: "📄",
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

  const siteKey = useMemo(() => {
    if (!user) {
      return "JLL";
    }
    if (user.role === "admin") {
      return siteContext?.override_site_key ?? user.site_key ?? "JLL";
    }
    return user.site_key ?? "JLL";
  }, [siteContext?.override_site_key, user]);

  const menuStorageKey = useMemo(() => {
    if (!user) {
      return null;
    }
    return `menu:order:${siteKey}:${user.username}`;
  }, [siteKey, user]);

  const defaultMenuItems = useMemo<MenuItem[]>(
    () => [
      {
        id: "home",
        type: "link",
        label: "Accueil",
        tooltip: "Accéder à la page d'accueil personnalisée",
        icon: "🏠",
        to: "/"
      },
      ...navigationGroups.map<MenuItem>((group) => ({
        id: group.id,
        type: "group",
        label: group.label,
        tooltip: group.tooltip,
        icon: group.icon,
        group
      }))
    ],
    [navigationGroups]
  );

  const defaultMenuIds = useMemo(
    () => defaultMenuItems.map((item) => item.id),
    [defaultMenuItems]
  );

  const [isReorderMode, setIsReorderMode] = useState(false);
  const [orderedIds, setOrderedIds] = useState<string[]>([]);

  useEffect(() => {
    if (!menuStorageKey) {
      return;
    }
    setOrderedIds(loadMenuOrder(menuStorageKey, defaultMenuIds));
  }, [defaultMenuIds, menuStorageKey]);

  const orderedMenuItems = useMemo(
    () => applyOrder(defaultMenuItems, orderedIds.length > 0 ? orderedIds : defaultMenuIds),
    [defaultMenuItems, defaultMenuIds, orderedIds]
  );

  const orderedMenuIds = useMemo(
    () => orderedMenuItems.map((item) => item.id),
    [orderedMenuItems]
  );

  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { distance: 6 } })
  );

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) {
      return;
    }
    const activeId = String(active.id);
    const overId = String(over.id);
    setOrderedIds((prev) => {
      const current = prev.length > 0 ? prev : defaultMenuIds;
      const oldIndex = current.indexOf(activeId);
      const newIndex = current.indexOf(overId);
      if (oldIndex === -1 || newIndex === -1) {
        return current;
      }
      const next = arrayMove(current, oldIndex, newIndex);
      if (menuStorageKey) {
        saveMenuOrder(menuStorageKey, next);
      }
      return next;
    });
  };

  const resetMenuOrder = () => {
    if (typeof window !== "undefined" && menuStorageKey) {
      window.localStorage.removeItem(menuStorageKey);
    }
    setOrderedIds(defaultMenuIds);
  };

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

  const isSidebarExpanded = isDesktop && sidebarOpen;
  const showPopoverMenu = isDesktop && !sidebarOpen;
  const navLinkHandler = mobileDrawerOpen ? () => setMobileDrawerOpen(false) : undefined;
  const activeSiteLabel = siteKey;

  const handleNavLinkClick = (
    event: MouseEvent<HTMLAnchorElement>,
    onNavigate?: () => void
  ) => {
    if (isReorderMode) {
      event.preventDefault();
      return;
    }
    onNavigate?.();
  };

  const handleGroupClick = (groupId: string) => {
    if (isReorderMode) {
      return;
    }
    toggleGroup(groupId);
  };

  const renderMenuItems = (options: {
    expanded: boolean;
    showPopover: boolean;
    onNavigate?: () => void;
  }) =>
    orderedMenuItems.map((item) => {
      if (item.type === "link") {
        return (
          <SortableMenuItem key={item.id} id={item.id} isEditMode={isReorderMode} isPinned={item.isPinned}>
            <NavLink
              to={item.to}
              end
              className={({ isActive }) => navClass(isActive, options.expanded)}
              title={item.tooltip}
              onClick={(event) => handleNavLinkClick(event, options.onNavigate)}
            >
              <NavIcon symbol={item.icon} label={item.label} />
              <span className={options.expanded ? "block" : "sr-only"}>{item.label}</span>
            </NavLink>
          </SortableMenuItem>
        );
      }

      const group = item.group;
      const isOpen = openGroups[group.id] ?? false;

      return (
        <SortableMenuItem key={group.id} id={group.id} isEditMode={isReorderMode} isPinned={item.isPinned}>
          <div className="relative w-full">
            <button
              type="button"
              onClick={() => handleGroupClick(group.id)}
              className={`group flex w-full items-center rounded-md font-semibold text-slate-200 transition-colors hover:bg-slate-800 ${
                options.expanded ? "justify-between px-3 py-2" : "h-11 justify-center"
              }`}
              aria-expanded={isOpen}
              aria-disabled={isReorderMode}
              title={group.tooltip}
            >
              <span className="flex items-center gap-3">
                <NavIcon symbol={group.icon} label={group.label} />
                <span className={options.expanded ? "block text-left" : "sr-only"}>{group.label}</span>
              </span>
              {options.expanded ? <span aria-hidden>{isOpen ? "−" : "+"}</span> : null}
            </button>
            {isOpen && options.expanded ? (
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
                          className={({ isActive }) => navClass(isActive, options.expanded)}
                          title={link.tooltip}
                          onClick={(event) => handleNavLinkClick(event, options.onNavigate)}
                        >
                          <NavIcon symbol={link.icon} label={link.label} />
                          <span>{link.label}</span>
                        </NavLink>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            ) : null}
            {isOpen && options.showPopover ? (
              <div className="fixed left-20 top-4 bottom-4 z-30 ml-3 w-72 max-w-[90vw] overflow-y-auto rounded-lg border border-slate-800 bg-slate-900 p-3 text-left shadow-2xl">
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
                          onClick={(event) => {
                            if (isReorderMode) {
                              event.preventDefault();
                              return;
                            }
                            toggleGroup(group.id);
                            options.onNavigate?.();
                          }}
                        >
                          <NavIcon symbol={link.icon} label={link.label} />
                          <span>{link.label}</span>
                        </NavLink>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </SortableMenuItem>
      );
    });

  return (
    <div className="flex h-screen min-h-0 overflow-hidden bg-slate-950 text-slate-50">
      <aside
        className={`relative flex h-full min-h-0 shrink-0 flex-col border-r border-slate-800 bg-slate-900 transition-all duration-200 ${
          isDesktop ? (sidebarOpen ? "w-64 p-6" : "w-20 p-4") : "w-14 p-3"
        }`}
      >
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Link to="/" className="block text-lg font-semibold" title="Revenir à l'accueil">
              <span aria-hidden>{isSidebarExpanded ? "Gestion Stock Pro" : "GSP"}</span>
              <span className="sr-only">Gestion Stock Pro</span>
            </Link>
            {isDebugActive ? (
              <span className="rounded bg-red-600 px-2 py-1 text-[10px] font-bold uppercase tracking-wide text-white">
                DEBUG
              </span>
            ) : null}
          </div>
          {isDesktop ? (
            <button
              type="button"
              onClick={toggleSidebar}
              className="rounded-md border border-slate-800 bg-slate-900 p-2 text-slate-200 shadow hover:bg-slate-800"
              aria-label={sidebarOpen ? "Réduire le menu principal" : "Déplier le menu principal"}
            >
              <span aria-hidden>{sidebarOpen ? "⟨" : "⟩"}</span>
            </button>
          ) : (
            <button
              type="button"
              onClick={() => setMobileDrawerOpen(true)}
              className="rounded-md border border-slate-800 bg-slate-900 p-2 text-slate-200 shadow hover:bg-slate-800"
              aria-label="Ouvrir le menu principal"
            >
              <span aria-hidden>☰</span>
            </button>
          )}
        </div>
        {isDesktop ? (
          <>
            <div
              className={`mt-8 flex min-h-0 flex-1 flex-col ${
                isSidebarExpanded ? "overflow-hidden" : "overflow-visible"
              }`}
            >
              <div
                className={`mb-4 flex flex-wrap items-center gap-2 ${
                  isSidebarExpanded ? "" : "justify-center"
                }`}
              >
                <button
                  type="button"
                  onClick={() => setIsReorderMode((prev) => !prev)}
                  className={`rounded-md border border-slate-800 bg-slate-900 text-xs font-semibold text-slate-200 shadow hover:bg-slate-800 ${
                    isSidebarExpanded ? "px-3 py-2" : "px-2 py-2"
                  }`}
                  aria-pressed={isReorderMode}
                >
                  <span aria-hidden>{isReorderMode ? "✓" : "↕"}</span>
                  <span className={isSidebarExpanded ? "ml-2" : "sr-only"}>
                    {isReorderMode ? "Terminer" : "Réorganiser"}
                  </span>
                </button>
                <button
                  type="button"
                  onClick={resetMenuOrder}
                  className={`rounded-md border border-slate-800 bg-slate-900 text-xs font-semibold text-slate-200 shadow hover:bg-slate-800 ${
                    isSidebarExpanded ? "px-3 py-2" : "px-2 py-2"
                  }`}
                >
                  <span aria-hidden>↺</span>
                  <span className={isSidebarExpanded ? "ml-2" : "sr-only"}>Réinitialiser</span>
                </button>
              </div>
              <nav
                className={`flex min-h-0 flex-1 flex-col gap-3 text-sm ${
                  isSidebarExpanded ? "overflow-y-auto pr-2" : "overflow-visible items-center"
                }`}
              >
                <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
                  <SortableContext items={orderedMenuIds} strategy={verticalListSortingStrategy}>
                    {renderMenuItems({
                      expanded: isSidebarExpanded,
                      showPopover: showPopoverMenu,
                      onNavigate: navLinkHandler
                    })}
                  </SortableContext>
                </DndContext>
              </nav>
              {modulePermissions.isLoading && user?.role !== "admin" ? (
                <p className="mt-3 text-xs text-slate-500">Chargement des modules autorisés...</p>
              ) : null}
            </div>
            <div className="mt-auto flex w-full flex-col gap-3 pt-6">
              <div
                className={`flex items-center gap-2 rounded-md border border-slate-800 bg-slate-900 text-xs text-slate-300 ${
                  isSidebarExpanded ? "px-3 py-2" : "px-2 py-1 justify-center"
                }`}
              >
                <NavIcon symbol={user.username.charAt(0).toUpperCase()} label={user.username} />
                <div className={isSidebarExpanded ? "leading-tight" : "sr-only"}>
                  <p className="font-semibold text-slate-200">{user.username}</p>
                  <p>Rôle : {user.role}</p>
                </div>
                {!isSidebarExpanded ? <span className="sr-only">Rôle : {user.role}</span> : null}
              </div>
              <MicToggle compact={!isSidebarExpanded} />
              <ThemeToggle compact={!isSidebarExpanded} />
              <button
                onClick={logout}
                className={`flex items-center justify-center gap-2 rounded-md bg-red-500 text-sm font-semibold text-white shadow hover:bg-red-400 ${
                  isSidebarExpanded ? "px-3 py-2" : "px-2 py-2"
                }`}
                title="Se déconnecter de votre session"
              >
                <span aria-hidden>⎋</span>
                <span className={isSidebarExpanded ? "block" : "sr-only"}>Se déconnecter</span>
              </button>
            </div>
          </>
        ) : null}
      </aside>
      {mobileDrawerOpen && isMobile ? (
        <div
          className="fixed inset-0 z-40 flex items-start justify-start p-2 sm:p-4 md:hidden"
          role="presentation"
          onClick={() => setMobileDrawerOpen(false)}
        >
          <div className="absolute inset-0 bg-black/40 backdrop-blur-[1px]" />
          <div
            ref={drawerRef}
            role="dialog"
            aria-modal="true"
            aria-label="Menu principal"
            className="relative z-50 flex max-h-[calc(100dvh-1rem)] w-11/12 max-w-sm flex-col overflow-hidden rounded-2xl border border-slate-800 bg-slate-900 text-slate-50 shadow-2xl sm:max-w-md"
            onClick={(event) => event.stopPropagation()}
            tabIndex={-1}
          >
            <div className="flex items-center justify-between gap-2 border-b border-slate-800 px-4 py-3">
              <div className="flex items-center gap-2">
                <Link to="/" className="block text-base font-semibold" title="Revenir à l'accueil">
                  <span aria-hidden>Gestion Stock Pro</span>
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
                onClick={() => setMobileDrawerOpen(false)}
                className="rounded-md border border-slate-800 bg-slate-900 p-2 text-slate-200 shadow hover:bg-slate-800"
                aria-label="Fermer le menu principal"
              >
                <span aria-hidden>✕</span>
              </button>
            </div>
            <div className="flex min-h-0 flex-1 flex-col px-4 pb-4 pt-3">
              <div className="mb-4 flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => setIsReorderMode((prev) => !prev)}
                  className="rounded-md border border-slate-800 bg-slate-900 px-3 py-2 text-xs font-semibold text-slate-200 shadow hover:bg-slate-800"
                  aria-pressed={isReorderMode}
                >
                  <span aria-hidden>{isReorderMode ? "✓" : "↕"}</span>
                  <span className="ml-2">{isReorderMode ? "Terminer" : "Réorganiser"}</span>
                </button>
                <button
                  type="button"
                  onClick={resetMenuOrder}
                  className="rounded-md border border-slate-800 bg-slate-900 px-3 py-2 text-xs font-semibold text-slate-200 shadow hover:bg-slate-800"
                >
                  <span aria-hidden>↺</span>
                  <span className="ml-2">Réinitialiser</span>
                </button>
              </div>
              <nav className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pr-1 text-sm">
                <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
                  <SortableContext items={orderedMenuIds} strategy={verticalListSortingStrategy}>
                    {renderMenuItems({
                      expanded: true,
                      showPopover: false,
                      onNavigate: navLinkHandler
                    })}
                  </SortableContext>
                </DndContext>
              </nav>
              <div className="mt-6 flex w-full flex-col gap-3">
                <div className="flex items-center gap-2 rounded-md border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-300">
                  <NavIcon symbol={user.username.charAt(0).toUpperCase()} label={user.username} />
                  <div className="leading-tight">
                    <p className="font-semibold text-slate-200">{user.username}</p>
                    <p>Rôle : {user.role}</p>
                  </div>
                </div>
                <MicToggle compact />
                <ThemeToggle compact />
                <button
                  onClick={logout}
                  className="flex items-center justify-center gap-2 rounded-md bg-red-500 px-3 py-2 text-sm font-semibold text-white shadow hover:bg-red-400"
                  title="Se déconnecter de votre session"
                >
                  <span aria-hidden>⎋</span>
                  <span>Se déconnecter</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
      <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-auto bg-slate-950 p-6">
        <div className="flex items-center justify-end pb-4">
          <span className="rounded-full border border-slate-800 bg-slate-900 px-3 py-1 text-xs font-semibold text-slate-200">
            Site: {activeSiteLabel}
          </span>
        </div>
        <Outlet />
      </main>
    </div>
  );
}

type SortableMenuItemProps = {
  id: string;
  isEditMode: boolean;
  isPinned?: boolean;
  children: ReactNode;
};

function SortableMenuItem({ id, isEditMode, isPinned, children }: SortableMenuItemProps) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } =
    useSortable({
      id,
      disabled: !isEditMode || isPinned
    });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`flex w-full items-start ${isEditMode ? "gap-2" : ""} ${
        isDragging ? "opacity-60" : ""
      }`}
    >
      {isEditMode ? (
        <button
          type="button"
          ref={setActivatorNodeRef}
          className={`flex h-8 w-8 items-center justify-center rounded-md border border-slate-800 bg-slate-900 text-slate-300 shadow transition hover:bg-slate-800 ${
            isPinned ? "cursor-not-allowed opacity-40" : ""
          }`}
          aria-label="Réorganiser l'élément du menu"
          {...attributes}
          {...listeners}
        >
          <span aria-hidden>≡</span>
        </button>
      ) : null}
      <div className="min-w-0 flex-1">{children}</div>
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
