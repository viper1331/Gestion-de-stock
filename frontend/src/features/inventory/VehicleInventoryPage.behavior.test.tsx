import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useEffect, useRef } from "react";

import {
  buildDropRequestPayload,
  resolveTargetView
} from "./VehicleInventoryPage";
import { useThrottledHoverState } from "./useThrottledHoverState";
import { useViewSelectionLock } from "./useViewSelectionLock";

function HoverTester() {
  const { isHovering, requestHoverState } = useThrottledHoverState(false, 50);
  const renderCountRef = useRef(0);
  renderCountRef.current += 1;

  useEffect(() => {
    // noop to react to changes in tests
  }, [isHovering]);

  return (
    <div>
      <span data-testid="hover-state">{isHovering ? "on" : "off"}</span>
      <span data-testid="render-count">{renderCountRef.current}</span>
      <button
        type="button"
        onClick={() => requestHoverState(true)}
        data-testid="trigger-hover"
      >
        trigger
      </button>
    </div>
  );
}

function ViewLockTester() {
  const { selectedView, requestViewChange, lockViewSelection, unlockViewSelection } =
    useViewSelectionLock("VUE A");

  return (
    <div>
      <span data-testid="current-view">{selectedView ?? "none"}</span>
      <button type="button" data-testid="lock" onClick={lockViewSelection}>
        lock
      </button>
      <button type="button" data-testid="unlock" onClick={unlockViewSelection}>
        unlock
      </button>
      <button
        type="button"
        data-testid="switch-view"
        onClick={() => requestViewChange("VUE B")}
      >
        switch
      </button>
    </div>
  );
}

describe("Vehicle inventory interactions", () => {
  it("throttles dragover updates to avoid infinite re-render loops", () => {
    vi.useFakeTimers();
    render(<HoverTester />);

    const trigger = screen.getByTestId("trigger-hover");

    act(() => {
      fireEvent.click(trigger);
      fireEvent.click(trigger);
      fireEvent.click(trigger);
      vi.advanceTimersByTime(25);
      fireEvent.click(trigger);
      vi.advanceTimersByTime(24);
    });

    expect(screen.getByTestId("hover-state").textContent).toBe("off");

    act(() => {
      vi.advanceTimersByTime(1);
    });

    expect(screen.getByTestId("hover-state").textContent).toBe("on");

    const renderCount = Number(screen.getByTestId("render-count").textContent);
    expect(renderCount).toBeGreaterThan(0);
    expect(renderCount).toBeLessThan(6);

    vi.useRealTimers();
  });

  it("keeps the view locked during drag operations", () => {
    render(<ViewLockTester />);

    expect(screen.getByTestId("current-view").textContent).toBe("VUE A");

    fireEvent.click(screen.getByTestId("lock"));
    fireEvent.click(screen.getByTestId("switch-view"));

    expect(screen.getByTestId("current-view").textContent).toBe("VUE A");

    fireEvent.click(screen.getByTestId("unlock"));

    expect(screen.getByTestId("current-view").textContent).toBe("VUE B");
  });

  it("uses the active incendie view for assignments", () => {
    const dropRequest = buildDropRequestPayload({
      itemId: 10,
      categoryId: 99,
      selectedView: "Vue cabine",
      position: { x: 0.1, y: 0.2 }
    });

    expect(dropRequest.targetView).toBe("VUE CABINE");
    expect(resolveTargetView("Vue active incendie")).toBe("VUE ACTIVE INCENDIE");
  });

  it("sends coherent API parameters on drop", () => {
    const dropRequest = buildDropRequestPayload({
      itemId: 5,
      categoryId: 7,
      selectedView: "Vue principale",
      position: { x: 0.5, y: 0.5 },
      sourceCategoryId: null,
      remiseItemId: 3,
      pharmacyItemId: null,
      quantity: 2
    });

    expect(dropRequest).toMatchObject({
      itemId: 5,
      categoryId: 7,
      sourceCategoryId: null,
      remiseItemId: 3,
      pharmacyItemId: null,
      targetView: "VUE PRINCIPALE"
    });
  });
});
