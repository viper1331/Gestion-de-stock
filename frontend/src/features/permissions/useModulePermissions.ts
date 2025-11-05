import { useMemo } from "react";
import { useQuery, UseQueryOptions } from "@tanstack/react-query";

import { api } from "../../lib/api";

const MODULE_DEPENDENCIES: Record<string, string[]> = {
  suppliers: ["clothing"],
  dotations: ["clothing"]
};

function collectDependencies(module: string): string[] {
  const resolved: string[] = [];
  const seen = new Set<string>();
  const stack = [...(MODULE_DEPENDENCIES[module] ?? [])];
  while (stack.length > 0) {
    const current = stack.pop();
    if (!current || seen.has(current)) {
      continue;
    }
    seen.add(current);
    resolved.push(current);
    const next = MODULE_DEPENDENCIES[current];
    if (next) {
      stack.push(...next);
    }
  }
  return resolved;
}

export interface ModulePermission {
  id: number;
  user_id: number;
  module: string;
  can_view: boolean;
  can_edit: boolean;
}

export function useModulePermissions(
  options?: Pick<UseQueryOptions<ModulePermission[], Error>, "enabled">
) {
  const query = useQuery({
    queryKey: ["module-permissions", "me"],
    queryFn: async () => {
      const response = await api.get<ModulePermission[]>("/permissions/modules/me");
      return response.data;
    },
    ...options
  });

  const canAccess = useMemo(() => {
    return (module: string, action: "view" | "edit" = "view") => {
      const permission = query.data?.find((entry) => entry.module === module);
      if (!permission) {
        return false;
      }
      const dependencies = collectDependencies(module);
      for (const dependency of dependencies) {
        const dependencyPermission = query.data?.find((entry) => entry.module === dependency);
        if (!dependencyPermission?.can_view) {
          return false;
        }
      }
      if (action === "edit") {
        return permission.can_edit;
      }
      return permission.can_view;
    };
  }, [query.data]);

  return { ...query, canAccess };
}

