import { describe, expect, it } from "vitest";

import { mergeMenuOrder, type MenuOrderConfig } from "./menuOrder";

type TestItem = { id: string; label: string };
type TestGroup = { id: string; items: TestItem[] };

const defaultGroups: TestGroup[] = [
  {
    id: "group_a",
    items: [
      { id: "a1", label: "A1" },
      { id: "a2", label: "A2" }
    ]
  },
  {
    id: "group_b",
    items: [
      { id: "b1", label: "B1" },
      { id: "b2", label: "B2" }
    ]
  }
];

describe("mergeMenuOrder", () => {
  it("reorders items within a group", () => {
    const saved: MenuOrderConfig = {
      version: 1,
      items: [
        { id: "a2", parentId: "group_a", order: 0 },
        { id: "a1", parentId: "group_a", order: 1 }
      ]
    };

    const result = mergeMenuOrder(defaultGroups, saved);
    expect(result[0].items.map((item) => item.id)).toEqual(["a2", "a1"]);
  });

  it("moves items across groups", () => {
    const saved: MenuOrderConfig = {
      version: 1,
      items: [{ id: "a1", parentId: "group_b", order: 0 }]
    };

    const result = mergeMenuOrder(defaultGroups, saved);
    expect(result[1].items.map((item) => item.id)).toEqual(["a1", "b1", "b2"]);
    expect(result[0].items.map((item) => item.id)).toEqual(["a2"]);
  });

  it("ignores unknown item ids", () => {
    const saved: MenuOrderConfig = {
      version: 1,
      items: [{ id: "unknown", parentId: "group_a", order: 0 }]
    };

    const result = mergeMenuOrder(defaultGroups, saved);
    expect(result[0].items.map((item) => item.id)).toEqual(["a1", "a2"]);
  });

  it("appends new items missing from saved order", () => {
    const saved: MenuOrderConfig = {
      version: 1,
      items: [{ id: "a2", parentId: "group_a", order: 0 }]
    };

    const result = mergeMenuOrder(defaultGroups, saved);
    expect(result[0].items.map((item) => item.id)).toEqual(["a2", "a1"]);
  });
});
