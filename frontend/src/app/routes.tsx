import { createBrowserRouter } from "react-router-dom";

import { AuthLayout } from "../features/auth/AuthLayout";
import { Login } from "../features/auth/Login";
import { AppLayout } from "../components/AppLayout";
import { HomePage } from "../features/home/HomePage";
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
import { AdminSettingsPage } from "../features/admin/AdminSettingsPage";
import { PurchaseOrdersPage } from "../features/inventory/PurchaseOrdersPage";
import { VehicleInventoryPage } from "../features/inventory/VehicleInventoryPage";
import { RemiseInventoryPage } from "../features/inventory/RemiseInventoryPage";
import { UpdatesPage } from "../features/updates/UpdatesPage";
import { VehicleQrManagerPage } from "../features/inventory/VehicleQrManagerPage";
import { VehicleGuidePage } from "../features/inventory/VehicleGuidePage";
import { AboutPage } from "../features/about/AboutPage";
import { SystemConfigPage } from "../features/system-config/SystemConfigPage";
import { MessagesPage } from "../features/messages/MessagesPage";
import { PdfStudioPage } from "../features/pdf-config/PdfStudioPage";

export const router = createBrowserRouter([
  {
    path: "/vehicle-guides/:qrToken",
    element: <VehicleGuidePage />
  },
  {
    path: "/login",
    element: <AuthLayout />,
    children: [{ path: "", element: <Login /> }]
  },
  {
    path: "/*",
    element: <AppLayout />,
    children: [
      { path: "", element: <HomePage /> },
      { path: "inventory", element: <Dashboard /> },
      { path: "vehicle-inventory", element: <VehicleInventoryPage /> },
      { path: "vehicle-inventory/qr-codes", element: <VehicleQrManagerPage /> },
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
      { path: "updates", element: <UpdatesPage /> },
      { path: "admin-settings", element: <AdminSettingsPage /> },
      { path: "system-config", element: <SystemConfigPage /> },
      { path: "about", element: <AboutPage /> },
      { path: "messages", element: <MessagesPage /> },
      { path: "pdf-config", element: <PdfStudioPage /> }
    ]
  }
]);
