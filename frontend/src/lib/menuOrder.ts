type MenuItem = {
  id: string;
};

export function loadMenuOrder(storageKey: string, defaultIds: string[]): string[] {
  if (typeof window === "undefined") {
    return defaultIds;
  }
  const storedValue = window.localStorage.getItem(storageKey);
  if (!storedValue) {
    return defaultIds;
  }
  try {
    const parsed = JSON.parse(storedValue);
    if (!Array.isArray(parsed)) {
      return defaultIds;
    }
    const normalized = parsed.filter((id): id is string => typeof id === "string");
    return normalized.length > 0 ? normalized : defaultIds;
  } catch {
    return defaultIds;
  }
}

export function saveMenuOrder(storageKey: string, ids: string[]): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(storageKey, JSON.stringify(ids));
}

export function applyOrder<T extends MenuItem>(defaultItems: T[], ids: string[]): T[] {
  const itemsById = new Map(defaultItems.map((item) => [item.id, item]));
  const orderedItems = ids.map((id) => itemsById.get(id)).filter(Boolean) as T[];
  const remainingItems = defaultItems.filter((item) => !ids.includes(item.id));
  return [...orderedItems, ...remainingItems];
}
