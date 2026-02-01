import { describe, expect, it } from "vitest";

import { filterMenuGroups, type MenuGroupDefinition } from "./menuVisibility";

describe("filterMenuGroups", () => {
  const baseGroup: MenuGroupDefinition = {
    id: "main",
    label: "Main",
    tooltip: "Main",
    items: [
      {
        id: "ari",
        to: "/ari",
        label: "ARI",
        tooltip: "ARI",
        module: "ari"
      }
    ]
  };

  it("hides ARI menu when the feature flag is disabled", () => {
    const result = filterMenuGroups([baseGroup], {
      user: { role: "user" },
      modulePermissions: { canAccess: () => true },
      featureAriEnabled: false
    });

    expect(result).toEqual([]);
  });

  it("keeps ARI menu when the feature flag is enabled", () => {
    const result = filterMenuGroups([baseGroup], {
      user: { role: "user" },
      modulePermissions: { canAccess: () => true },
      featureAriEnabled: true
    });

    expect(result[0]?.items).toHaveLength(1);
    expect(result[0]?.items[0]?.id).toBe("ari");
  });
});
