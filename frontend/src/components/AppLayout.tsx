import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useEffect, useMemo, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  DndContext,
  DragCancelEvent,
  DragEndEvent,
  DragOverEvent,
  DragStartEvent,
  MouseSensor,
  TouchSensor,
  closestCenter,
  useDroppable,
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
import { getMenuOrder, setMenuOrder, type MenuOrderPayload } from "../api/uiMenu";
import { fetchConfigEntries } from "../lib/config";
import { fetchSiteContext } from "../lib/sites";
import { buildModuleTitleMap } from "../lib/moduleTitles";
import { isDebugEnabled } from "../lib/debug";
import { mergeMenuOrder } from "../lib/menuOrder";
import { useIdleLogout } from "../hooks/useIdleLogout";

type MenuItem = {
  id: string;
  label: string;
  tooltip: string;
  icon?: string;
  to: string;
};

type MenuItemDefinition = MenuItem & {
  module?: string;
  modules?: string[];
  adminOnly?: boolean;
};

type MenuGroup = {
  id: string;
  label: string;
  tooltip: string;
  icon?: string;
  items: MenuItem[];
};

type MenuGroupDefinition = Omit<MenuGroup, "items"> & {
  items: MenuItemDefinition[];
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
  const [isReorderMode, setIsReorderMode] = useState(false);
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

  useIdleLogout();

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
      const groups: MenuGroupDefinition[] = [
        {
          id: "home_group",
          label: "Accueil",
          tooltip: "Accéder à la page d'accueil personnalisée",
          icon: "🏠",
          items: [
            {
              id: "home",
              to: "/",
              label: "Accueil",
              tooltip: "Accéder à la page d'accueil personnalisée",
              icon: "🏠"
            }
          ]
        },
        {
          id: "barcode_group",
          label: moduleTitles.barcode,
          tooltip: "Accéder aux outils de codes-barres",
          icon: "🏷️",
          items: [
            {
              id: "barcode",
              to: "/barcode",
              label: moduleTitles.barcode,
              tooltip: "Générer et scanner les codes-barres",
              icon: "📌",
              module: "barcode"
            }
          ]
        },
        {
          id: "clothing_group",
          label: moduleTitles.clothing,
          tooltip: "Accéder aux fonctionnalités d'habillement",
          icon: "🧥",
          items: [
            {
              id: "clothing_dashboard",
              to: "/inventory",
              label: moduleTitles.clothing,
              tooltip: "Consulter le tableau de bord habillement",
              icon: "📦",
              module: "clothing"
            },
            {
              id: "clothing_reports",
              to: "/reports",
              label: "Rapports",
              tooltip: "Analyser les rapports d'habillement",
              icon: "📈",
              module: "clothing"
            },
            {
              id: "clothing_purchase_orders",
              to: "/purchase-orders",
              label: "Bons de commande",
              tooltip: "Gérer les bons de commande d'habillement",
              icon: "🧾",
              module: "clothing"
            },
            {
              id: "suppliers",
              to: "/suppliers",
              label: moduleTitles.suppliers,
              tooltip: "Gérer les fournisseurs d'habillement",
              icon: "🏭",
              module: "suppliers"
            },
            {
              id: "collaborators",
              to: "/collaborators",
              label: "Collaborateurs",
              tooltip: "Suivre les collaborateurs et leurs dotations",
              icon: "👥",
              module: "dotations"
            },
            {
              id: "dotations",
              to: "/dotations",
              label: moduleTitles.dotations,
              tooltip: "Attribuer les dotations d'habillement",
              icon: "🎯",
              module: "dotations"
            }
          ]
        },
        {
          id: "specialized_group",
          label: "Inventaires spécialisés",
          tooltip: "Accéder aux inventaires véhicules et remises",
          icon: "🚚",
          items: [
            {
              id: "vehicle_inventory",
              to: "/vehicle-inventory",
              label: moduleTitles.vehicle_inventory,
              tooltip: "Gérer le parc véhicules",
              icon: "🚗",
              module: "vehicle_inventory"
            },
            {
              id: "vehicle_qrcodes",
              to: "/vehicle-inventory/qr-codes",
              label: moduleTitles.vehicle_qrcodes,
              tooltip: "Partager les fiches matériel via QR codes",
              icon: "🔖",
              modules: ["vehicle_qrcodes", "vehicle_inventory"]
            },
            {
              id: "remise_inventory",
              to: "/remise-inventory",
              label: moduleTitles.inventory_remise,
              tooltip: "Suivre les stocks mis en remise",
              icon: "🏢",
              module: "inventory_remise"
            }
          ]
        },
        {
          id: "pharmacy_group",
          label: moduleTitles.pharmacy,
          tooltip: "Accéder aux fonctionnalités de pharmacie",
          icon: "💊",
          items: [
            {
              id: "pharmacy",
              to: "/pharmacy",
              label: moduleTitles.pharmacy,
              tooltip: "Consulter le tableau de bord pharmacie",
              icon: "🏥",
              module: "pharmacy"
            }
          ]
        },
        {
          id: "communication_group",
          label: "Communication",
          tooltip: "Échanger des messages internes",
          icon: "💬",
          items: [
            {
              id: "messages",
              to: "/messages",
              label: "Messagerie",
              tooltip: "Ouvrir la messagerie interne",
              icon: "✉️"
            }
          ]
        },
        {
          id: "operations_group",
          label: "Opérations",
          tooltip: "Accéder aux opérations terrain",
          icon: "🛠️",
          items: [
            {
              id: "operations_vehicle_qr",
              to: "/operations/vehicle-qr",
              label: "QR codes véhicules",
              tooltip: "Gérer les liens et QR codes véhicules",
              icon: "🔖",
              modules: ["vehicle_qrcodes", "vehicle_inventory"]
            },
            {
              id: "operations_pharmacy_links",
              to: "/operations/pharmacy-links",
              label: "Liens Pharmacie",
              tooltip: "Gérer les liens associés aux articles pharmacie",
              icon: "💊",
              module: "pharmacy"
            },
            {
              id: "operations_link_categories",
              to: "/operations/link-categories",
              label: "Configuration liens",
              tooltip: "Configurer les catégories de liens",
              icon: "⚙️",
              adminOnly: true
            }
          ]
        },
        {
          id: "admin_group",
          label: "Administration",
          tooltip: "Paramétrer votre environnement",
          icon: "🛠️",
          items: [
            {
              id: "settings",
              to: "/settings",
              label: "Paramètres",
              tooltip: "Configurer les paramètres généraux",
              icon: "⚙️",
            },
            {
              id: "admin_settings",
              to: "/admin-settings",
              label: "Paramètres avancés",
              tooltip: "Configurer les types de véhicules et champs personnalisés",
              icon: "🧩",
              adminOnly: true
            },
            {
              id: "system_config",
              to: "/system-config",
              label: "Configuration système",
              tooltip: "Ajuster les URLs publiques et les origines autorisées",
              icon: "🌐",
              adminOnly: true
            },
            {
              id: "pdf_config",
              to: "/pdf-config",
              label: "Configuration PDF",
              tooltip: "Personnaliser les exports PDF",
              icon: "📄",
              adminOnly: true
            },
            {
              id: "users",
              to: "/users",
              label: "Utilisateurs",
              tooltip: "Administrer les comptes utilisateurs",
              icon: "👤",
              adminOnly: true
            },
            {
              id: "permissions",
              to: "/permissions",
              label: "Permissions",
              tooltip: "Gérer les droits d'accès",
              icon: "🔒",
              adminOnly: true
            },
            {
              id: "updates",
              to: "/updates",
              label: "Mises à jour",
              tooltip: "Gérer les mises à jour GitHub du serveur",
              icon: "⬆️",
              adminOnly: true
            }
          ]
        },
        {
          id: "support_group",
          label: "Support",
          tooltip: "Consulter les informations du programme",
          icon: "ℹ️",
          items: [
            {
              id: "about",
              to: "/about",
              label: "À propos",
              tooltip: "Consulter la licence et la version en ligne",
              icon: "📘",
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
          items: group.items.filter((item) => {
            if (item.adminOnly) {
              return user?.role === "admin";
            }
            const allowedModules = item.modules ?? (item.module ? [item.module] : []);
            if (allowedModules.length === 0) {
              return true;
            }
            if (user.role === "admin") {
              return true;
            }
            return allowedModules.some((module) => modulePermissions.canAccess(module));
          })
        }))
        .filter((group) => group.items.length > 0)
        .map((group) => ({
          id: group.id,
          label: group.label,
          tooltip: group.tooltip,
          icon: group.icon,
          items: group.items.map(({ adminOnly, module, modules, ...item }) => item)
        }));
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

  const defaultMenuGroups = useMemo<MenuGroup[]>(() => navigationGroups, [navigationGroups]);

  const [menuGroups, setMenuGroups] = useState<MenuGroup[]>([]);
  const [savedMenuOrder, setSavedMenuOrder] = useState<MenuOrderPayload | null>(null);
  const [menuOrderError, setMenuOrderError] = useState<string | null>(null);
  const [isMenuOrderLoading, setIsMenuOrderLoading] = useState(false);

  useEffect(() => {
    if (isReorderMode && isDesktop && !sidebarOpen) {
      toggleSidebar();
    }
  }, [isDesktop, isReorderMode, sidebarOpen, toggleSidebar]);

  useEffect(() => {
    if (!user) {
      setMenuGroups([]);
      setSavedMenuOrder(null);
      return;
    }
    let isActive = true;
    setIsMenuOrderLoading(true);
    setMenuOrderError(null);
    getMenuOrder()
      .then((savedConfig) => {
        if (!isActive) {
          return;
        }
        setSavedMenuOrder(
          savedConfig ? { version: savedConfig.version, items: savedConfig.items } : null
        );
      })
      .catch(() => {
        if (!isActive) {
          return;
        }
        setMenuOrderError("Impossible de charger l'ordre du menu.");
        setSavedMenuOrder(null);
      })
      .finally(() => {
        if (!isActive) {
          return;
        }
        setIsMenuOrderLoading(false);
      });
    return () => {
      isActive = false;
    };
  }, [siteKey, user]);

  useEffect(() => {
    if (!user) {
      return;
    }
    setMenuGroups(mergeMenuOrder(defaultMenuGroups, savedMenuOrder));
  }, [defaultMenuGroups, savedMenuOrder, user]);

  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { distance: 6 } })
  );

  const menuGroupsRef = useRef(menuGroups);
  const previousMenuGroupsRef = useRef<MenuGroup[] | null>(null);

  useEffect(() => {
    menuGroupsRef.current = menuGroups;
  }, [menuGroups]);

  const buildMenuOrderPayload = (groups: MenuGroup[]): MenuOrderPayload => ({
    version: 1,
    items: groups.flatMap((group, groupIndex) => [
      { id: group.id, parentId: null, order: groupIndex },
      ...group.items.map((item, itemIndex) => ({
        id: item.id,
        parentId: group.id,
        order: itemIndex
      }))
    ])
  });

  const persistMenuOrder = async (nextGroups: MenuGroup[], previousGroups: MenuGroup[]) => {
    try {
      const savedOrder = await setMenuOrder(buildMenuOrderPayload(nextGroups));
      setMenuOrderError(null);
      setSavedMenuOrder({ version: savedOrder.version, items: savedOrder.items });
      setMenuGroups(mergeMenuOrder(defaultMenuGroups, savedOrder));
    } catch (error) {
      console.error("Menu order update failed", error);
      setMenuOrderError("Impossible d'enregistrer l'ordre du menu.");
      setMenuGroups(previousGroups);
    }
  };

  const findGroupIdForItem = (groups: MenuGroup[], itemId: string) =>
    groups.find((group) => group.items.some((item) => item.id === itemId))?.id;

  const moveItemWithinGroup = (
    groups: MenuGroup[],
    groupId: string,
    activeId: string,
    overId: string
  ) => {
    const nextGroups = groups.map((group) => {
      if (group.id !== groupId) {
        return group;
      }
      const oldIndex = group.items.findIndex((item) => item.id === activeId);
      const newIndexRaw = group.items.findIndex((item) => item.id === overId);
      if (oldIndex === -1) {
        return group;
      }
      const newIndex = newIndexRaw === -1 ? group.items.length - 1 : newIndexRaw;
      return {
        ...group,
        items: arrayMove(group.items, oldIndex, newIndex)
      };
    });
    return nextGroups;
  };

  const moveItemAcrossGroups = (
    groups: MenuGroup[],
    activeId: string,
    sourceGroupId: string,
    targetGroupId: string,
    overId: string
  ) => {
    if (sourceGroupId === targetGroupId) {
      return groups;
    }
    let movingItem: MenuItem | undefined;
    const nextGroups = groups.map((group) => {
      if (group.id === sourceGroupId) {
        const nextItems = group.items.filter((item) => {
          if (item.id === activeId) {
            movingItem = item;
            return false;
          }
          return true;
        });
        return { ...group, items: nextItems };
      }
      return group;
    });

    const movingItemResolved = movingItem;
    if (!movingItemResolved) {
      return groups;
    }

    return nextGroups.map((group) => {
      if (group.id !== targetGroupId) {
        return group;
      }
      const indexInTarget = group.items.findIndex((item) => item.id === overId);
      const insertIndex = indexInTarget === -1 ? group.items.length : indexInTarget;
      const nextItems = [...group.items];
      nextItems.splice(insertIndex, 0, movingItemResolved);
      return { ...group, items: nextItems };
    });
  };

  const handleDragStart = (event: DragStartEvent) => {
    if (!isReorderMode) {
      return;
    }
    previousMenuGroupsRef.current = menuGroupsRef.current;
  };

  const handleDragOver = (event: DragOverEvent) => {
    if (!isReorderMode) {
      return;
    }
    const { active, over } = event;
    if (!over) {
      return;
    }
    const activeId = String(active.id);
    const overId = String(over.id);
    if (activeId === overId) {
      return;
    }
    const currentGroups = menuGroupsRef.current;
    const activeGroupId = findGroupIdForItem(currentGroups, activeId);
    const overGroupId =
      findGroupIdForItem(currentGroups, overId) ??
      (currentGroups.some((group) => group.id === overId) ? overId : undefined);
    if (!activeGroupId || !overGroupId || activeGroupId === overGroupId) {
      return;
    }
    setMenuGroups((prev) => moveItemAcrossGroups(prev, activeId, activeGroupId, overGroupId, overId));
  };

  const handleDragEnd = (event: DragEndEvent) => {
    if (!isReorderMode) {
      return;
    }
    const { active, over } = event;
    const previousGroups = previousMenuGroupsRef.current;
    previousMenuGroupsRef.current = null;
    if (!over || !previousGroups) {
      return;
    }
    const activeId = String(active.id);
    const overId = String(over.id);
    if (activeId === overId) {
      return;
    }
    const currentGroups = menuGroupsRef.current;
    const activeGroupId = findGroupIdForItem(currentGroups, activeId);
    const overGroupId =
      findGroupIdForItem(currentGroups, overId) ??
      (currentGroups.some((group) => group.id === overId) ? overId : undefined);
    if (!activeGroupId || !overGroupId) {
      return;
    }

    let nextGroups = currentGroups;
    if (activeGroupId === overGroupId) {
      nextGroups = moveItemWithinGroup(currentGroups, activeGroupId, activeId, overId);
    } else {
      nextGroups = moveItemAcrossGroups(currentGroups, activeId, activeGroupId, overGroupId, overId);
    }

    if (nextGroups !== currentGroups) {
      setMenuGroups(nextGroups);
    }
    void persistMenuOrder(nextGroups, previousGroups);
  };

  const handleDragCancel = (_event: DragCancelEvent) => {
    const previousGroups = previousMenuGroupsRef.current;
    previousMenuGroupsRef.current = null;
    if (previousGroups) {
      setMenuGroups(previousGroups);
    }
  };

  const resetMenuOrder = () => {
    const previousGroups = menuGroupsRef.current;
    setMenuGroups(defaultMenuGroups);
    void persistMenuOrder(defaultMenuGroups, previousGroups);
  };

  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({});
  const previousOpenGroupsRef = useRef<Record<string, boolean> | null>(null);

  useEffect(() => {
    setOpenGroups((prev) => {
      const next: Record<string, boolean> = {};
      let hasChanges = false;
      const groupIds = new Set(menuGroups.map((group) => group.id));

      menuGroups.forEach((group) => {
        const previousValue =
          prev[group.id] ??
          (group.id === "home_group" ? true : false);
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
  }, [menuGroups]);

  useEffect(() => {
    if (isReorderMode) {
      if (!previousOpenGroupsRef.current) {
        previousOpenGroupsRef.current = openGroups;
      }
      setOpenGroups(Object.fromEntries(menuGroups.map((group) => [group.id, true])));
      return;
    }
    if (previousOpenGroupsRef.current) {
      setOpenGroups(previousOpenGroupsRef.current);
      previousOpenGroupsRef.current = null;
    }
  }, [isReorderMode, menuGroups]);

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

  const handleReload = () => {
    window.location.reload();
  };

  const renderMenuItems = (options: {
    expanded: boolean;
    showPopover: boolean;
    onNavigate?: () => void;
  }) =>
    menuGroups.map((group) => {
      const isOpen = openGroups[group.id] ?? false;
      const shouldShowItems = isReorderMode || isOpen;

      const renderItemsList = (isExpanded: boolean, closeOnNavigate: boolean) => (
        <MenuGroupItems
          key={`${group.id}-items-${isExpanded ? "expanded" : "compact"}`}
          groupId={group.id}
          isEditMode={isReorderMode}
          isExpanded={isExpanded}
        >
          <SortableContext items={group.items.map((item) => item.id)} strategy={verticalListSortingStrategy}>
            {group.items.map((link) => (
              <SortableMenuItem key={link.id} id={link.id} isEditMode={isReorderMode}>
                <NavLink
                  to={link.to}
                  end={link.to === "/" || link.to === "/inventory"}
                  className={({ isActive }) => navClass(isActive, isExpanded)}
                  title={link.tooltip}
                  onClick={(event) => {
                    handleNavLinkClick(event, options.onNavigate);
                    if (!isReorderMode && closeOnNavigate) {
                      toggleGroup(group.id);
                    }
                  }}
                >
                  <NavIcon symbol={link.icon} label={link.label} />
                  <span>{link.label}</span>
                </NavLink>
              </SortableMenuItem>
            ))}
            {group.items.length === 0 ? (
              <p className="px-3 py-2 text-xs text-slate-500">Aucun élément dans ce groupe.</p>
            ) : null}
          </SortableContext>
        </MenuGroupItems>
      );

      return (
        <div key={group.id} className="relative w-full">
          <button
            type="button"
            onClick={() => handleGroupClick(group.id)}
            className={`MenuItem group flex w-full items-center rounded-md font-semibold text-slate-200 transition-colors hover:bg-slate-800 ${
              options.expanded ? "min-h-[48px] justify-between px-3 py-2" : "h-11 justify-center"
            }`}
            aria-expanded={shouldShowItems}
            aria-disabled={isReorderMode}
            title={group.tooltip}
          >
            <span className="flex items-center gap-2">
              <NavIcon symbol={group.icon} label={group.label} />
              <span className={options.expanded ? "block text-left" : "sr-only"}>{group.label}</span>
            </span>
            {options.expanded ? (
              <span
                aria-hidden
                className="flex h-8 w-8 items-center justify-center rounded-md text-base text-slate-300"
              >
                {shouldShowItems ? "−" : "+"}
              </span>
            ) : null}
          </button>
          {shouldShowItems && options.expanded ? (
            <div className="mt-2 border-l border-slate-800 pl-3">{renderItemsList(true, false)}</div>
          ) : null}
          {shouldShowItems && options.showPopover ? (
            <div className="fixed left-20 top-4 bottom-4 z-30 ml-3 w-72 max-w-[90vw] overflow-y-auto rounded-lg border border-slate-800 bg-slate-900 p-3 text-left shadow-2xl">
              {renderItemsList(true, true)}
            </div>
          ) : null}
        </div>
      );
    });

  return (
    <div className="flex h-screen min-h-0 overflow-hidden bg-slate-950 text-slate-50">
      <aside
        className={`Sidebar relative shrink-0 border-r border-slate-800 bg-slate-900 transition-all duration-200 ${
          isDesktop ? (sidebarOpen ? "w-64 px-4 py-3" : "w-20 p-3") : "w-14 p-3"
        }`}
      >
        <div className="SidebarHeader flex items-center justify-between gap-2">
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
              className={`SidebarModules mt-4 flex min-h-0 flex-1 flex-col ${
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
                {isReorderMode ? (
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
                ) : null}
              </div>
              {isMenuOrderLoading ? (
                <p className="mb-2 text-xs text-slate-500">Chargement de l'ordre du menu...</p>
              ) : null}
              {menuOrderError ? (
                <p className="mb-2 text-xs text-red-300">{menuOrderError}</p>
              ) : null}
              <nav
                className={`flex min-h-0 flex-1 flex-col gap-2 text-sm ${
                  isSidebarExpanded ? "overflow-y-auto pr-2" : "overflow-visible items-center"
                }`}
              >
                <DndContext
                  sensors={sensors}
                  collisionDetection={closestCenter}
                  onDragStart={handleDragStart}
                  onDragOver={handleDragOver}
                  onDragEnd={handleDragEnd}
                  onDragCancel={handleDragCancel}
                >
                  {renderMenuItems({
                    expanded: isSidebarExpanded,
                    showPopover: showPopoverMenu && !isReorderMode,
                    onNavigate: navLinkHandler
                  })}
                </DndContext>
              </nav>
              {modulePermissions.isLoading && user?.role !== "admin" ? (
                <p className="mt-3 text-xs text-slate-500">Chargement des modules autorisés...</p>
              ) : null}
            </div>
            <div className="SidebarPinned mt-auto flex w-full flex-col gap-2 pt-3">
              <div
                className={`flex items-center gap-2 rounded-md border border-slate-800 bg-slate-900 text-xs text-slate-300 ${
                  isSidebarExpanded ? "px-3 py-2" : "px-2 py-1.5 justify-center"
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
                onClick={handleReload}
                className={`flex items-center justify-center gap-2 rounded-md border border-slate-800 bg-slate-900 text-sm font-semibold text-slate-200 shadow hover:bg-slate-800 ${
                  isSidebarExpanded ? "px-3 py-2" : "px-2 py-1.5"
                }`}
                title="Recharger l'application"
              >
                <span aria-hidden>⟳</span>
                <span className={isSidebarExpanded ? "block" : "sr-only"}>Recharger</span>
              </button>
              <button
                onClick={() => logout()}
                className={`flex items-center justify-center gap-2 rounded-md bg-red-500 text-sm font-semibold text-white shadow hover:bg-red-400 ${
                  isSidebarExpanded ? "px-3 py-2" : "px-2 py-1.5"
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
          onClick={() => {
            if (isReorderMode) {
              return;
            }
            setMobileDrawerOpen(false);
          }}
        >
          <div className="absolute inset-0 bg-black/40 backdrop-blur-[1px]" />
          <div
            ref={drawerRef}
            role="dialog"
            aria-modal="true"
            aria-label="Menu principal"
            className="Sidebar relative z-50 flex max-h-[calc(100dvh-1rem)] w-11/12 max-w-sm flex-col overflow-hidden rounded-2xl border border-slate-800 bg-slate-900 text-slate-50 shadow-2xl sm:max-w-md"
            onClick={(event) => event.stopPropagation()}
            tabIndex={-1}
          >
            <div className="SidebarHeader flex items-center justify-between gap-2 border-b border-slate-800 px-4 py-3">
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
            <div className="SidebarModules flex min-h-0 flex-1 flex-col px-4 pb-3 pt-2">
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
                {isReorderMode ? (
                  <button
                    type="button"
                    onClick={resetMenuOrder}
                    className="rounded-md border border-slate-800 bg-slate-900 px-3 py-2 text-xs font-semibold text-slate-200 shadow hover:bg-slate-800"
                  >
                    <span aria-hidden>↺</span>
                    <span className="ml-2">Réinitialiser</span>
                  </button>
                ) : null}
              </div>
              {isMenuOrderLoading ? (
                <p className="mb-2 text-xs text-slate-500">Chargement de l'ordre du menu...</p>
              ) : null}
              {menuOrderError ? (
                <p className="mb-2 text-xs text-red-300">{menuOrderError}</p>
              ) : null}
              <nav className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto pr-1 text-sm">
                <DndContext
                  sensors={sensors}
                  collisionDetection={closestCenter}
                  onDragStart={handleDragStart}
                  onDragOver={handleDragOver}
                  onDragEnd={handleDragEnd}
                  onDragCancel={handleDragCancel}
                >
                  {renderMenuItems({
                    expanded: true,
                    showPopover: false,
                    onNavigate: navLinkHandler
                  })}
                </DndContext>
              </nav>
            </div>
            <div className="SidebarPinned mt-4 flex w-full flex-col gap-2 px-4 pb-3">
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
                  onClick={handleReload}
                  className="flex items-center justify-center gap-2 rounded-md border border-slate-800 bg-slate-900 px-3 py-2 text-sm font-semibold text-slate-200 shadow hover:bg-slate-800"
                  title="Recharger l'application"
                >
                  <span aria-hidden>⟳</span>
                  <span>Recharger</span>
                </button>
                <button
                  onClick={() => logout()}
                  className="flex items-center justify-center gap-2 rounded-md bg-red-500 px-3 py-2 text-sm font-semibold text-white shadow hover:bg-red-400"
                  title="Se déconnecter de votre session"
                >
                  <span aria-hidden>⎋</span>
                  <span>Se déconnecter</span>
                </button>
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
  children: ReactNode;
};

type MenuGroupItemsProps = {
  groupId: string;
  isEditMode: boolean;
  isExpanded: boolean;
  children: ReactNode;
};

function MenuGroupItems({ groupId, isEditMode, isExpanded, children }: MenuGroupItemsProps) {
  const { setNodeRef, isOver } = useDroppable({ id: groupId });
  return (
    <div
      ref={setNodeRef}
      className={`flex flex-col gap-1 ${isExpanded ? "" : "items-center"} ${
        isEditMode ? "min-h-[2.5rem]" : ""
      } ${isOver ? "rounded-md bg-slate-800/40 p-1" : ""}`}
    >
      {children}
    </div>
  );
}

function SortableMenuItem({ id, isEditMode, children }: SortableMenuItemProps) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } =
    useSortable({
      id,
      disabled: !isEditMode
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
          className="flex h-8 w-8 items-center justify-center rounded-md border border-slate-800 bg-slate-900 text-slate-300 shadow transition hover:bg-slate-800"
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
  return `MenuItem flex items-center gap-2 rounded-md font-medium transition-colors ${
    expanded ? "min-h-[48px] px-3 py-2" : "h-11 w-full justify-center"
  } ${isActive ? "bg-slate-800 text-white shadow-sm" : "text-slate-300 hover:bg-slate-800"}`;
}

function NavIcon({ symbol, label }: { symbol?: string; label: string }) {
  return (
    <span aria-hidden className="MenuIcon flex items-center justify-center rounded-full border border-slate-800 bg-slate-800/60">
      {symbol ?? label.charAt(0)}
    </span>
  );
}
