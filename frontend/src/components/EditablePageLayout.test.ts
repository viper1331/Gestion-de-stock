import { describe, expect, it } from "vitest";

import {
  applyVisibleOrder,
  extractOrderFromLayouts,
  mergeOrder,
  type EditableLayoutSet
} from "./EditablePageLayout";

describe("EditablePageLayout helpers", () => {
  it("merges saved order with defaults", () => {
    const defaults = ["header", "filters", "table", "orders"];
    const saved = ["table", "header"];

    expect(mergeOrder(defaults, saved)).toEqual(["table", "header", "filters", "orders"]);
  });

  it("applies visible order while keeping hidden positions", () => {
    const fullOrder = ["a", "b", "c", "d"];
    const hidden = new Set(["b"]);
    const visibleOrder = ["d", "a", "c"];

    expect(applyVisibleOrder(fullOrder, visibleOrder, hidden)).toEqual(["d", "b", "a", "c"]);
  });

  it("extracts order from saved layouts", () => {
    const layouts: EditableLayoutSet = {
      lg: [
        { i: "filters", x: 0, y: 0, w: 12, h: 8 },
        { i: "table", x: 0, y: 9, w: 12, h: 12 }
      ],
      md: [],
      sm: [],
      xs: []
    };

    expect(extractOrderFromLayouts(layouts)).toEqual(["filters", "table"]);
  });
});
