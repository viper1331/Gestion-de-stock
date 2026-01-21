import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "../lib/api";

export type TablePrefs = {
  v: 1;
  visible?: Record<string, boolean>;
  order?: string[];
  widths?: Record<string, number>;
};

type TablePrefsResponse = {
  table_key: string;
  prefs: TablePrefs;
};

const SAVE_DEBOUNCE_MS = 500;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const normalizePrefs = (prefs: TablePrefs): TablePrefs => ({
  v: 1,
  visible: prefs.visible ? { ...prefs.visible } : undefined,
  order: prefs.order ? [...prefs.order] : undefined,
  widths: prefs.widths ? { ...prefs.widths } : undefined
});

const mergePrefs = (defaults: TablePrefs, saved?: TablePrefs | null): TablePrefs => {
  const base = normalizePrefs(defaults);
  if (!saved) {
    return base;
  }
  const next: TablePrefs = {
    v: 1,
    visible: base.visible ? { ...base.visible } : undefined,
    order: base.order ? [...base.order] : undefined,
    widths: base.widths ? { ...base.widths } : undefined
  };
  const availableColumns = new Set<string>([
    ...(base.order ?? []),
    ...Object.keys(base.visible ?? {}),
    ...Object.keys(base.widths ?? {})
  ]);
  if (saved.visible && isRecord(saved.visible)) {
    next.visible = next.visible ?? {};
    Object.entries(saved.visible).forEach(([key, value]) => {
      if (availableColumns.has(key) && typeof value === "boolean") {
        next.visible![key] = value;
      }
    });
  }
  if (saved.widths && isRecord(saved.widths)) {
    next.widths = next.widths ?? {};
    Object.entries(saved.widths).forEach(([key, value]) => {
      if (availableColumns.has(key) && typeof value === "number") {
        next.widths![key] = value;
      }
    });
  }
  if (Array.isArray(saved.order)) {
    const sanitized = saved.order.filter(
      (key): key is string => typeof key === "string" && availableColumns.has(key)
    );
    const defaultOrder = base.order ?? Array.from(availableColumns);
    const deduped = Array.from(new Set(sanitized));
    const missing = defaultOrder.filter((key) => !deduped.includes(key));
    next.order = [...deduped, ...missing];
  }
  return next;
};

export function useTablePrefs(tableKey: string, defaults: TablePrefs) {
  const [prefs, setPrefs] = useState<TablePrefs>(() => mergePrefs(defaults));
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const hasLoaded = useRef(false);
  const savingRef = useRef(false);
  const pendingRef = useRef<TablePrefs | null>(null);
  const debounceRef = useRef<number | null>(null);
  const skipNextSaveRef = useRef(false);
  const defaultsRef = useRef<TablePrefs>(defaults);

  useEffect(() => {
    defaultsRef.current = defaults;
    if (!hasLoaded.current) {
      setPrefs(mergePrefs(defaults));
      return;
    }
    setPrefs((current) => mergePrefs(defaults, current));
  }, [defaults]);

  useEffect(() => {
    let isActive = true;
    const fetchPrefs = async () => {
      setIsLoading(true);
      try {
        const response = await api.get<TablePrefsResponse | null>(
          `/ui/table-prefs/${encodeURIComponent(tableKey)}`
        );
        const merged = mergePrefs(defaultsRef.current, response.data?.prefs);
        if (isActive) {
          setPrefs(merged);
        }
      } catch {
        if (isActive) {
          setPrefs(mergePrefs(defaultsRef.current));
        }
      } finally {
        if (isActive) {
          setIsLoading(false);
          hasLoaded.current = true;
        }
      }
    };
    fetchPrefs();
    return () => {
      isActive = false;
    };
  }, [tableKey]);

  const savePrefs = useCallback(async (nextPrefs: TablePrefs) => {
    if (savingRef.current) {
      pendingRef.current = nextPrefs;
      return;
    }
    savingRef.current = true;
    setIsSaving(true);
    try {
      await api.put(`/ui/table-prefs/${encodeURIComponent(tableKey)}`, {
        prefs: nextPrefs
      });
    } finally {
      savingRef.current = false;
      setIsSaving(false);
      if (pendingRef.current) {
        const pending = pendingRef.current;
        pendingRef.current = null;
        void savePrefs(pending);
      }
    }
  }, [tableKey]);

  useEffect(() => {
    if (!hasLoaded.current || isLoading) {
      return undefined;
    }
    if (skipNextSaveRef.current) {
      skipNextSaveRef.current = false;
      return undefined;
    }
    if (debounceRef.current) {
      window.clearTimeout(debounceRef.current);
    }
    debounceRef.current = window.setTimeout(() => {
      void savePrefs(prefs);
    }, SAVE_DEBOUNCE_MS);
    return () => {
      if (debounceRef.current) {
        window.clearTimeout(debounceRef.current);
      }
    };
  }, [prefs, isLoading, savePrefs]);

  const setVisible = useCallback((columnKey: string, value?: boolean) => {
    setPrefs((current) => {
      const visible = { ...(current.visible ?? {}) };
      const isVisible = visible[columnKey] !== false;
      const nextValue = value ?? !isVisible;
      visible[columnKey] = nextValue;
      return { ...current, visible };
    });
  }, []);

  const setOrder = useCallback((order: string[]) => {
    setPrefs((current) => ({ ...current, order: [...order] }));
  }, []);

  const setWidth = useCallback((columnKey: string, width: number) => {
    setPrefs((current) => {
      const widths = { ...(current.widths ?? {}) };
      widths[columnKey] = width;
      return { ...current, widths };
    });
  }, []);

  const reset = useCallback(async () => {
    skipNextSaveRef.current = true;
    setPrefs(mergePrefs(defaultsRef.current));
    await api.delete(`/ui/table-prefs/${encodeURIComponent(tableKey)}`);
  }, [tableKey]);

  return useMemo(
    () => ({
      prefs,
      setVisible,
      setOrder,
      setWidth,
      reset,
      isLoading,
      isSaving
    }),
    [prefs, setVisible, setOrder, setWidth, reset, isLoading, isSaving]
  );
}
