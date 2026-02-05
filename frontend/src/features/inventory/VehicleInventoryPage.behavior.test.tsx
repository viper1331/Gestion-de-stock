import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  buildDropRequestPayload,
  filterPinnedSubviews,
  resolveTargetView
} from "./VehicleInventoryPage";
import { useThrottledHoverState } from "./useThrottledHoverState";
import { useViewSelectionLock } from "./useViewSelectionLock";

describe("Vehicle inventory interactions", () => {
  it("throttles dragover updates to avoid infinite re-render loops", () => {
    const { result } = renderHook(() => useThrottledHoverState(50));
    const rect = new DOMRect(0, 0, 100, 100);
    const nowSpy = vi.spyOn(performance, "now");

    nowSpy.mockReturnValue(100);
    act(() => {
      result.current.handleHover({ clientX: 25, clientY: 75 } as DragEvent, rect);
    });

    expect(result.current.hoverRef.current).toBe(true);
    expect(result.current.posRef.current).toEqual({ x: 0.25, y: 0.75 });

    nowSpy.mockReturnValue(120);
    act(() => {
      result.current.handleHover({ clientX: 50, clientY: 50 } as DragEvent, rect);
    });

    expect(result.current.posRef.current).toEqual({ x: 0.25, y: 0.75 });

    nowSpy.mockReturnValue(200);
    act(() => {
      result.current.handleHover({ clientX: 50, clientY: 50 } as DragEvent, rect);
    });

    expect(result.current.posRef.current).toEqual({ x: 0.5, y: 0.5 });

    nowSpy.mockRestore();
  });

  it("keeps the view locked during drag operations", () => {
    const { result } = renderHook(() => useViewSelectionLock());

    act(() => {
      result.current.lock("VUE A");
    });

    expect(result.current.getLockedView("VUE B")).toBe("VUE A");

    act(() => {
      result.current.unlock();
    });

    expect(result.current.getLockedView("VUE B")).toBe("VUE B");
  });

  it("uses the active incendie view for assignments", () => {
    const dropRequest = buildDropRequestPayload({
      sourceType: "vehicle",
      sourceId: 10,
      vehicleItemId: 10,
      categoryId: 99,
      selectedView: "Vue cabine",
      position: { x: 0.1, y: 0.2 }
    });

    expect(dropRequest.targetView).toBe("VUE CABINE");
    expect(resolveTargetView("Vue active incendie")).toBe("VUE ACTIVE INCENDIE");
  });

  it("sends coherent API parameters on drop", () => {
    const dropRequest = buildDropRequestPayload({
      sourceType: "remise",
      sourceId: 3,
      vehicleItemId: null,
      categoryId: 7,
      selectedView: "Vue principale",
      position: { x: 0.5, y: 0.5 },
      sourceCategoryId: null,
      remiseItemId: 3,
      pharmacyItemId: null,
      quantity: 2
    });

    expect(dropRequest).toMatchObject({
      sourceType: "remise",
      sourceId: 3,
      categoryId: 7,
      sourceCategoryId: null,
      remiseItemId: 3,
      pharmacyItemId: null,
      targetView: "VUE PRINCIPALE"
    });
  });

  it("pins a subview when dropped and preserves order", () => {
    const pinned = ["CABINE - CASIER 2"];
    const nextPinned = filterPinnedSubviews({
      pinned: ["Cabine - Casier 1", ...pinned],
      availableSubViews: ["Cabine - Casier 1", "Cabine - Casier 2"],
      parentView: "Cabine"
    });

    expect(nextPinned).toEqual(["CABINE - CASIER 1", "CABINE - CASIER 2"]);
  });

  it("filters pinned subviews based on available views", () => {
    const filtered = filterPinnedSubviews({
      pinned: ["CABINE - CASIER 1", "COFFRE - B", "CABINE - CASIER 1"],
      availableSubViews: ["CABINE - CASIER 1", "CABINE - CASIER 2"],
      parentView: "Cabine"
    });

    expect(filtered).toEqual(["CABINE - CASIER 1"]);
  });
});
