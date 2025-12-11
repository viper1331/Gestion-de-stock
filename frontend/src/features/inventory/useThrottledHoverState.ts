// useThrottledHoverState.ts
import { useCallback, useRef } from "react";

export function useThrottledHoverState(throttleMs = 50) {
  const lastCall = useRef(0);
  const hoverRef = useRef(false);
  const posRef = useRef({ x: 0, y: 0 });

  const handleHover = useCallback((e: DragEvent, rect: DOMRect | null) => {
    const now = performance.now();
    if (now - lastCall.current < throttleMs) return;

    lastCall.current = now;
    hoverRef.current = true;

    if (rect) {
      posRef.current = {
        x: (e.clientX - rect.left) / rect.width,
        y: (e.clientY - rect.top) / rect.height,
      };
    }
  }, []);

  const resetHover = () => {
    hoverRef.current = false;
  };

  return {
    hoverRef,
    posRef,
    handleHover,
    resetHover,
  };
}
