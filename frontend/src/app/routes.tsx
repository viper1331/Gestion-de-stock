import { createBrowserRouter } from "react-router-dom";

import { AuthLayout } from "../features/auth/AuthLayout";
import { Login } from "../features/auth/Login";
import { AppLayout } from "../components/AppLayout";
import { Dashboard } from "../features/inventory/Dashboard";
import { BarcodePage } from "../features/barcode/BarcodePage";
import { ReportsPage } from "../features/reports/ReportsPage";
import { SettingsPage } from "../features/settings/SettingsPage";
import { SuppliersPage } from "../features/suppliers/SuppliersPage";
import { CollaboratorsPage } from "../features/dotations/CollaboratorsPage";
import { DotationsPage } from "../features/dotations/DotationsPage";
import { PharmacyPage } from "../features/pharmacy/PharmacyPage";
import { ModulePermissionsPage } from "../features/permissions/ModulePermissionsPage";
import { AdminUsersPage } from "../features/users/AdminUsersPage";
import { PurchaseOrdersPage } from "../features/inventory/PurchaseOrdersPage";
import { VehicleInventoryPage } from "../features/inventory/VehicleInventoryPage";
import { RemiseInventoryPage } from "../features/inventory/RemiseInventoryPage";
import { UpdatesPage } from "../features/updates/UpdatesPage";

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
      { path: "vehicle-inventory", element: <VehicleInventoryPage /> },
      { path: "remise-inventory", element: <RemiseInventoryPage /> },
      { path: "barcode", element: <BarcodePage /> },
      { path: "reports", element: <ReportsPage /> },
      { path: "purchase-orders", element: <PurchaseOrdersPage /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "suppliers", element: <SuppliersPage /> },
      { path: "collaborators", element: <CollaboratorsPage /> },
      { path: "dotations", element: <DotationsPage /> },
      { path: "pharmacy", element: <PharmacyPage /> },
      { path: "users", element: <AdminUsersPage /> },
      { path: "permissions", element: <ModulePermissionsPage /> },
      { path: "updates", element: <UpdatesPage /> }
    ]
  }
]);
