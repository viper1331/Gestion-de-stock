import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "../lib/api";
import { useAuthStore } from "../features/auth/authStore";

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

const LOCAL_STORAGE_PREFIX = "ui.table.layout";

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const normalizePrefs = (prefs: TablePrefs): TablePrefs => ({
  v: 1,
  visible: prefs.visible ? { ...prefs.visible } : undefined,
  order: prefs.order ? [...prefs.order] : undefined,
  widths: prefs.widths ? { ...prefs.widths } : undefined
});

const resolveModuleKey = (tableKey: string) => {
  const [moduleKey] = tableKey.split(".");
  return moduleKey?.trim() ? moduleKey.trim() : tableKey;
};

const buildStorageKey = (layoutKey: string) => `${LOCAL_STORAGE_PREFIX}:${layoutKey}`;

const loadStoredPrefs = (layoutKey: string): TablePrefs | null => {
  if (typeof window === "undefined") {
    return null;
  }
  const raw = window.localStorage.getItem(buildStorageKey(layoutKey));
  if (!raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw);
    if (!isRecord(parsed) || parsed.v !== 1) {
      return null;
    }
    return parsed as TablePrefs;
  } catch {
    return null;
  }
};

const saveStoredPrefs = (layoutKey: string, prefs: TablePrefs) => {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(buildStorageKey(layoutKey), JSON.stringify(normalizePrefs(prefs)));
  } catch {
    // Ignore local storage failures.
  }
};

const removeStoredPrefs = (layoutKey: string) => {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.removeItem(buildStorageKey(layoutKey));
  } catch {
    // Ignore local storage failures.
  }
};

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

export function useTablePrefs(
  tableKey: string,
  defaults: TablePrefs,
  options?: { moduleKey?: string }
) {
  const user = useAuthStore((state) => state.user);
  const moduleKey = useMemo(
    () => options?.moduleKey ?? resolveModuleKey(tableKey),
    [options?.moduleKey, tableKey]
  );
  const siteKey = user?.site_key ?? "unknown";
  const layoutKey = useMemo(
    () => (user ? `${siteKey}:${moduleKey}:${tableKey}:${user.id}` : null),
    [moduleKey, siteKey, tableKey, user]
  );
  const [prefs, setPrefs] = useState<TablePrefs>(() => {
    if (!layoutKey) {
      return mergePrefs(defaults);
    }
    return mergePrefs(defaults, loadStoredPrefs(layoutKey));
  });
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const defaultsRef = useRef<TablePrefs>(defaults);
  const prefsRef = useRef<TablePrefs>(prefs);
  const didHydrateRef = useRef(false);
  const lastSavedRef = useRef("");

  useEffect(() => {
    prefsRef.current = prefs;
  }, [prefs]);

  useEffect(() => {
    defaultsRef.current = defaults;
    setPrefs((current) => mergePrefs(defaults, current));
  }, [defaults]);

  useEffect(() => {
    let isActive = true;
    const fetchPrefs = async () => {
      if (!layoutKey) {
        didHydrateRef.current = false;
        setIsLoading(false);
        return;
      }
      setIsLoading(true);
      const localPrefs = loadStoredPrefs(layoutKey);
      const localMerged = mergePrefs(defaultsRef.current, localPrefs ?? undefined);
      if (isActive) {
        prefsRef.current = localMerged;
        setPrefs(localMerged);
      }
      try {
        const response = await api.get<TablePrefsResponse | null>(
          `/ui/table-prefs/${encodeURIComponent(tableKey)}`
        );
        const savedPrefs = response.data?.prefs ?? null;
        if (savedPrefs) {
          const merged = mergePrefs(defaultsRef.current, savedPrefs);
          if (isActive) {
            prefsRef.current = merged;
            setPrefs(merged);
          }
          saveStoredPrefs(layoutKey, merged);
          lastSavedRef.current = JSON.stringify(normalizePrefs(merged));
        } else {
          lastSavedRef.current = JSON.stringify(normalizePrefs(localMerged));
        }
      } catch {
        lastSavedRef.current = JSON.stringify(normalizePrefs(localMerged));
      } finally {
        if (isActive) {
          setIsLoading(false);
          didHydrateRef.current = true;
        }
      }
    };
    fetchPrefs();
    return () => {
      isActive = false;
    };
  }, [layoutKey, tableKey]);

  const updatePrefs = useCallback((updater: (current: TablePrefs) => TablePrefs) => {
    const next = updater(prefsRef.current);
    prefsRef.current = next;
    setPrefs(next);
    return next;
  }, []);

  const persistLayout = useCallback(
    async (nextPrefs: TablePrefs) => {
      if (!layoutKey || !didHydrateRef.current) {
        return;
      }
      const normalized = normalizePrefs(nextPrefs);
      const signature = JSON.stringify(normalized);
      if (signature === lastSavedRef.current) {
        return;
      }
      lastSavedRef.current = signature;
      saveStoredPrefs(layoutKey, normalized);
      setIsSaving(true);
      try {
        await api.put(`/ui/table-prefs/${encodeURIComponent(tableKey)}`, {
          prefs: normalized
        });
      } catch {
        // Backend unavailable; local storage already updated.
      } finally {
        setIsSaving(false);
      }
    },
    [layoutKey, tableKey]
  );

  const setVisible = useCallback((columnKey: string, value?: boolean) => {
    const next = updatePrefs((current) => {
      const visible = { ...(current.visible ?? {}) };
      const isVisible = visible[columnKey] !== false;
      const nextValue = value ?? !isVisible;
      visible[columnKey] = nextValue;
      return { ...current, visible };
    });
    void persistLayout(next);
  }, [persistLayout, updatePrefs]);

  const setOrder = useCallback((order: string[]) => {
    const next = updatePrefs((current) => ({ ...current, order: [...order] }));
    void persistLayout(next);
  }, [persistLayout, updatePrefs]);

  const setWidth = useCallback((columnKey: string, width: number) => {
    updatePrefs((current) => {
      const widths = { ...(current.widths ?? {}) };
      widths[columnKey] = width;
      return { ...current, widths };
    });
  }, [updatePrefs]);

  const reset = useCallback(async () => {
    const next = mergePrefs(defaultsRef.current);
    prefsRef.current = next;
    setPrefs(next);
    if (layoutKey) {
      removeStoredPrefs(layoutKey);
    }
    lastSavedRef.current = JSON.stringify(normalizePrefs(next));
    await api.delete(`/ui/table-prefs/${encodeURIComponent(tableKey)}`);
  }, [layoutKey, tableKey]);

  const persist = useCallback(() => {
    void persistLayout(prefsRef.current);
  }, [persistLayout]);

  return useMemo(
    () => ({
      prefs,
      setVisible,
      setOrder,
      setWidth,
      persist,
      reset,
      isLoading,
      isSaving
    }),
    [prefs, setVisible, setOrder, setWidth, persist, reset, isLoading, isSaving]
  );
}
