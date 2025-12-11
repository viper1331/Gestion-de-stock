// useViewSelectionLock.ts
import { useRef } from "react";

export function useViewSelectionLock() {
  const lockRef = useRef<string | null>(null);

  const lock = (view: string) => {
    if (lockRef.current === null) {
      lockRef.current = view;
    }
  };

  const unlock = () => {
    lockRef.current = null;
  };

  const getLockedView = (fallback: string) => {
    return lockRef.current ?? fallback;
  };

  return { lock, unlock, getLockedView };
}
