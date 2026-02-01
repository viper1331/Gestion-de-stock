export type MenuItem = {
  id: string;
  label: string;
  tooltip: string;
  icon?: string;
  to: string;
};

export type MenuItemDefinition = MenuItem & {
  module?: string;
  modules?: string[];
  adminOnly?: boolean;
};

export type MenuGroupDefinition = {
  id: string;
  label: string;
  tooltip: string;
  icon?: string;
  items: MenuItemDefinition[];
};

export type MenuGroup = {
  id: string;
  label: string;
  tooltip: string;
  icon?: string;
  items: MenuItem[];
};

type UserSummary = {
  role: string;
};

type ModulePermissionChecker = {
  canAccess: (module: string) => boolean;
};

export function filterMenuGroups(
  groups: MenuGroupDefinition[],
  options: {
    user: UserSummary | null;
    modulePermissions: ModulePermissionChecker;
    featureAriEnabled: boolean;
  }
): MenuGroup[] {
  const { user, modulePermissions, featureAriEnabled } = options;
  if (!user) {
    return [];
  }

  return groups
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => {
        if (item.adminOnly) {
          return user.role === "admin";
        }
        const allowedModules = item.modules ?? (item.module ? [item.module] : []);
        if (allowedModules.length === 0) {
          return true;
        }
        if (allowedModules.includes("ari")) {
          if (!featureAriEnabled) {
            return false;
          }
          if (user.role === "admin" || user.role === "certificateur") {
            return true;
          }
          return modulePermissions.canAccess("ari");
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
}
