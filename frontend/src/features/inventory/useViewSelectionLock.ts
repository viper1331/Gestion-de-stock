import { useCallback, useEffect, useRef, useState } from "react";

export function useViewSelectionLock(initialView: string | null = null) {
  const [selectedView, setSelectedView] = useState<string | null>(initialView);
  const selectedViewRef = useRef(selectedView);
  const freezeViewRef = useRef(false);
  const pendingViewRef = useRef<string | null>(null);

  useEffect(() => {
    selectedViewRef.current = selectedView;
  }, [selectedView]);

  const applyPendingView = useCallback(() => {
    if (pendingViewRef.current === null) {
      return;
    }
    const nextView = pendingViewRef.current;
    pendingViewRef.current = null;
    setSelectedView(nextView);
  }, []);

  const lockViewSelection = useCallback(() => {
    freezeViewRef.current = true;
  }, []);

  const unlockViewSelection = useCallback(() => {
    if (!freezeViewRef.current) {
      return;
    }
    freezeViewRef.current = false;
    applyPendingView();
  }, [applyPendingView]);

  const requestViewChange = useCallback(
    (next: string | null) => {
      if (freezeViewRef.current) {
        pendingViewRef.current = next;
        return;
      }
      setSelectedView(next);
    },
    []
  );

  const resetView = useCallback(() => {
    pendingViewRef.current = null;
    freezeViewRef.current = false;
    setSelectedView(initialView);
  }, [initialView]);

  return {
    selectedView,
    selectedViewRef,
    freezeViewRef,
    requestViewChange,
    lockViewSelection,
    unlockViewSelection,
    resetView
  } as const;
}
