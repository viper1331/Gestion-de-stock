import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { useEffect, useMemo } from "react";

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

  const navigationLinks = useMemo(
    () => {
      type NavLinkConfig = {
        to: string;
        label: string;
        module?: string;
        adminOnly?: boolean;
      };

      const baseLinks: NavLinkConfig[] = [
        { to: "/", label: "Inventaire" },
        { to: "/barcode", label: "Codes-barres" },
        { to: "/reports", label: "Rapports" },
        { to: "/suppliers", label: "Fournisseurs", module: "suppliers" },
        { to: "/collaborators", label: "Collaborateurs", module: "dotations" },
        { to: "/dotations", label: "Dotations", module: "dotations" },
        { to: "/pharmacy", label: "Pharmacie", module: "pharmacy" },
        { to: "/settings", label: "Paramètres" },
        { to: "/users", label: "Utilisateurs", adminOnly: true },
        { to: "/permissions", label: "Permissions", adminOnly: true }
      ];

      if (!user) {
        return [];
      }

      return baseLinks.filter((link) => {
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
      });
    },
    [modulePermissions.canAccess, user?.role]
  );

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
        <Link to="/" className="block text-lg font-semibold">
          Gestion Stock Pro
        </Link>
        <nav className="mt-8 flex flex-col gap-2 text-sm">
          {navigationLinks.map((link) => (
            <NavLink key={link.to} to={link.to} end={link.to === "/"} className={({ isActive }) => navClass(isActive)}>
              {link.label}
            </NavLink>
          ))}
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
