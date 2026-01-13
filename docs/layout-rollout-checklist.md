# EditablePageLayout Rollout Checklist

| Module | Route path | Component file path | pageKey | Blocks declared (IDs) | Status | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| Home | `/` | `frontend/src/features/home/HomePage.tsx` | `home` | `home-dashboard` | Migrated | EditablePageLayout already in place. |
| Inventory (Clothing) | `/inventory` | `frontend/src/features/inventory/InventoryModuleDashboard.tsx` | `module:clothing:inventory` | `inventory-main`, `inventory-orders` | Migrated | Layout uses shared table wrappers and EditablePageLayout. |
| Inventory (Vehicle) | `/vehicle-inventory` | `frontend/src/features/inventory/VehicleInventoryPage.tsx` | `module:vehicle:inventory` | `vehicle-header`, `vehicle-list`, `vehicle-detail` | Migrated | Added min-w-0 safeguards to prevent cut cards and overflow. |
| Inventory (Vehicle QR) | `/vehicle-inventory/qr-codes` | `frontend/src/features/inventory/VehicleQrManagerPage.tsx` | `module:vehicle:qr` | `vehicle-qr-main` | Migrated | EditablePageLayout already applied. |
| Inventory (Vehicle Guide) | `/vehicle-guides/:qrToken` | `frontend/src/features/inventory/VehicleGuidePage.tsx` | `module:vehicle:guide` | `vehicle-guide-main` | Migrated | Public QR page now uses EditablePageLayout (single block, no edit mode). |
| Inventory (Remise) | `/remise-inventory` | `frontend/src/features/inventory/RemiseInventoryPage.tsx` | `module:remise:inventory` | `remise-header`, `remise-filters`, `remise-items`, `remise-orders`, `remise-lots` | Migrated | Remise inventory now uses dedicated blocks for header, filters, inventory table, orders, and lots. |
| Barcode | `/barcode` | `frontend/src/features/barcode/BarcodePage.tsx` | `module:barcode` | `barcode-main` | Migrated | EditablePageLayout already applied. |
| Reports (Clothing) | `/reports` | `frontend/src/features/reports/ReportsPage.tsx` | `module:reports:clothing` | `reports-main` | Migrated | EditablePageLayout already applied. |
| Purchase Orders (Clothing) | `/purchase-orders` | `frontend/src/features/inventory/PurchaseOrdersPage.tsx` | `module:clothing:purchase-orders` | `purchase-orders-panel` | Migrated | EditablePageLayout already applied. |
| Suppliers | `/suppliers` | `frontend/src/features/suppliers/SuppliersPage.tsx` | `module:suppliers` | `suppliers-main` | Migrated | EditablePageLayout already applied. |
| Collaborators | `/collaborators` | `frontend/src/features/dotations/CollaboratorsPage.tsx` | `module:clothing:collaborators` | `collaborators-table`, `collaborators-form` | Migrated | EditablePageLayout already applied. |
| Dotations | `/dotations` | `frontend/src/features/dotations/DotationsPage.tsx` | `module:dotations` | `dotations-main` | Migrated | EditablePageLayout already applied. |
| Pharmacy | `/pharmacy` | `frontend/src/features/pharmacy/PharmacyPage.tsx` | `module:pharmacy:inventory` | `pharmacy-header`, `pharmacy-search`, `pharmacy-items`, `pharmacy-lots`, `pharmacy-low-stock`, `pharmacy-orders`, `pharmacy-side-panel`, `pharmacy-categories`, `pharmacy-stats` | Migrated | Split into header/search/items/side panel/stats blocks with lots/orders coverage and responsive tables. |
| Messages | `/messages` | `frontend/src/features/messages/MessagesPage.tsx` | `system:messages` | `messages-main` | Migrated | EditablePageLayout already applied. |
| Settings | `/settings` | `frontend/src/features/settings/SettingsPage.tsx` | `module:settings` | `settings-main` | Migrated | EditablePageLayout already applied. |
| Admin Settings | `/admin-settings` | `frontend/src/features/admin/AdminSettingsPage.tsx` | `admin:settings` | `admin-settings-main` | Migrated | EditablePageLayout already applied. |
| System Config | `/system-config` | `frontend/src/features/system-config/SystemConfigPage.tsx` | `admin:system-config` | `system-config-main` | Migrated | EditablePageLayout already applied. |
| PDF Studio | `/pdf-config` | `frontend/src/features/pdf-config/PdfStudioPage.tsx` | `module:pdf:studio` | `pdf-studio-main` | Migrated | EditablePageLayout already applied. |
| Admin Users | `/users` | `frontend/src/features/users/AdminUsersPage.tsx` | `admin:users` | `admin-users-main` | Migrated | EditablePageLayout already applied. |
| Permissions | `/permissions` | `frontend/src/features/permissions/ModulePermissionsPage.tsx` | `admin:permissions` | `permissions-main` | Migrated | EditablePageLayout already applied. |
| Updates | `/updates` | `frontend/src/features/updates/UpdatesPage.tsx` | `system:updates` | `updates-main` | Migrated | EditablePageLayout already applied. |
| About | `/about` | `frontend/src/features/about/AboutPage.tsx` | `system:about` | `about-main` | Migrated | EditablePageLayout already applied. |
