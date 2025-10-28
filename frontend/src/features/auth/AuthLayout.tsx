import { Outlet, useNavigate } from "react-router-dom";
import { useEffect } from "react";

import { useAuth } from "./useAuth";

export function AuthLayout() {
  const { user, initialize, isCheckingSession, isReady } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    initialize();
  }, [initialize]);

  useEffect(() => {
    if (isReady && user) {
      navigate("/", { replace: true });
    }
  }, [isReady, navigate, user]);

  if (!isReady || isCheckingSession) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950 text-slate-100">
        <p className="text-sm text-slate-300">Vérification de la session...</p>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 text-slate-50">
      <div className="w-full max-w-md rounded-xl border border-slate-800 bg-slate-900 p-10 shadow-xl">
        <Outlet />
      </div>
    </div>
  );
}
