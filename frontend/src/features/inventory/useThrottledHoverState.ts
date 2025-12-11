import { useCallback, useEffect, useRef, useState } from "react";

export function useThrottledHoverState(initialState = false, delayMs = 50) {
  const [isHovering, setIsHovering] = useState(initialState);
  const hoverIntentRef = useRef(isHovering);
  const throttleTimeoutRef = useRef<number | null>(null);

  useEffect(() => {
    hoverIntentRef.current = isHovering;
  }, [isHovering]);

  const flushHoverIntent = useCallback(() => {
    if (throttleTimeoutRef.current !== null) {
      return;
    }
    throttleTimeoutRef.current = window.setTimeout(() => {
      throttleTimeoutRef.current = null;
      setIsHovering(hoverIntentRef.current);
    }, delayMs);
  }, [delayMs]);

  const requestHoverState = useCallback(
    (nextState: boolean) => {
      hoverIntentRef.current = nextState;
      flushHoverIntent();
    },
    [flushHoverIntent]
  );

  const cancelHoverState = useCallback(() => {
    hoverIntentRef.current = false;
    if (throttleTimeoutRef.current !== null) {
      window.clearTimeout(throttleTimeoutRef.current);
      throttleTimeoutRef.current = null;
    }
    setIsHovering(false);
  }, []);

  useEffect(() => {
    return () => {
      if (throttleTimeoutRef.current !== null) {
        window.clearTimeout(throttleTimeoutRef.current);
      }
    };
  }, []);

  return { isHovering, requestHoverState, cancelHoverState } as const;
}
