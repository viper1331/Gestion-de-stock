import { useMemo } from "react";
import { useQuery, UseQueryOptions } from "@tanstack/react-query";

import { api } from "../../lib/api";

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
      if (action === "edit") {
        return permission.can_edit;
      }
      return permission.can_view;
    };
  }, [query.data]);

  return { ...query, canAccess };
}

