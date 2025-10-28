import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { useEffect } from "react";

import { useAuth } from "../features/auth/useAuth";
import { ThemeToggle } from "./ThemeToggle";

export function AppLayout() {
  const { user, logout, initialize, isReady, isCheckingSession } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    initialize();
  }, [initialize]);

  useEffect(() => {
    if (isReady && !user) {
      navigate("/login", { replace: true });
    }
  }, [isReady, navigate, user]);

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
          <NavLink to="/" end className={({ isActive }) => navClass(isActive)}>
            Inventaire
          </NavLink>
          <NavLink to="/barcode" className={({ isActive }) => navClass(isActive)}>
            Codes-barres
          </NavLink>
          <NavLink to="/reports" className={({ isActive }) => navClass(isActive)}>
            Rapports
          </NavLink>
          <NavLink to="/settings" className={({ isActive }) => navClass(isActive)}>
            Paramètres
          </NavLink>
        </nav>
        <div className="mt-auto flex flex-col gap-3 pt-6">
          <div className="rounded-md border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-300">
            <p className="font-semibold text-slate-200">{user.username}</p>
            <p>Rôle : {user.role}</p>
          </div>
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
