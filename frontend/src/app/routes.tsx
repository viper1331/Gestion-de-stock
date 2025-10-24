import { createBrowserRouter } from "react-router-dom";

import { AuthLayout } from "../features/auth/AuthLayout";
import { Login } from "../features/auth/Login";
import { AppLayout } from "../components/AppLayout";
import { Dashboard } from "../features/inventory/Dashboard";
import { BarcodePage } from "../features/barcode/BarcodePage";
import { ReportsPage } from "../features/reports/ReportsPage";
import { SettingsPage } from "../features/settings/SettingsPage";

export const router = createBrowserRouter([
  {
    path: "/login",
    element: <AuthLayout />,
    children: [{ path: "", element: <Login /> }]
  },
  {
    path: "/*",
    element: <AppLayout />,
    children: [
      { path: "", element: <Dashboard /> },
      { path: "barcode", element: <BarcodePage /> },
      { path: "reports", element: <ReportsPage /> },
      { path: "settings", element: <SettingsPage /> }
    ]
  }
]);
