type MenuItem = {
  id: string;
};

export function applyOrder<T extends MenuItem>(defaultItems: T[], ids: string[]): T[] {
  const itemsById = new Map(defaultItems.map((item) => [item.id, item]));
  const orderedItems = ids.map((id) => itemsById.get(id)).filter(Boolean) as T[];
  const idSet = new Set(ids);
  const remainingItems = defaultItems.filter((item) => !idSet.has(item.id));
  return [...orderedItems, ...remainingItems];
}
