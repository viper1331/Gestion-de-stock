export type MenuOrderItem = {
  id: string;
  parentId: string | null;
  order: number;
};

export type MenuOrderConfig = {
  version: number;
  items: MenuOrderItem[];
};

type MenuItemBase = {
  id: string;
};

type MenuGroupBase<TItem extends MenuItemBase> = {
  id: string;
  items: TItem[];
};

export function mergeMenuOrder<TItem extends MenuItemBase, TGroup extends MenuGroupBase<TItem>>(
  defaultGroups: TGroup[],
  savedConfig?: MenuOrderConfig | null
): TGroup[] {
  if (!savedConfig?.items?.length) {
    return defaultGroups;
  }

  const groupIds = new Set(defaultGroups.map((group) => group.id));
  const itemsById = new Map<string, TItem>();
  defaultGroups.forEach((group) => {
    group.items.forEach((item) => {
      itemsById.set(item.id, item);
    });
  });

  const savedByGroup = new Map<string, MenuOrderItem[]>();
  const seenItems = new Set<string>();
  const assignedItems = new Set<string>();

  savedConfig.items.forEach((item, index) => {
    if (!item || seenItems.has(item.id)) {
      return;
    }
    const targetGroup = item.parentId;
    if (!targetGroup || !groupIds.has(targetGroup)) {
      return;
    }
    if (!itemsById.has(item.id)) {
      return;
    }
    seenItems.add(item.id);
    assignedItems.add(item.id);
    const bucket = savedByGroup.get(targetGroup) ?? [];
    bucket.push({ ...item, order: Number.isFinite(item.order) ? item.order : index });
    savedByGroup.set(targetGroup, bucket);
  });

  return defaultGroups.map((group) => {
    const savedItems = (savedByGroup.get(group.id) ?? [])
      .slice()
      .sort((a, b) => a.order - b.order);
    const orderedItems = savedItems
      .map((item) => itemsById.get(item.id))
      .filter(Boolean) as TItem[];
    const orderedIds = new Set(orderedItems.map((item) => item.id));
    const remaining = group.items.filter(
      (item) => !orderedIds.has(item.id) && !assignedItems.has(item.id)
    );
    return {
      ...group,
      items: [...orderedItems, ...remaining]
    };
  });
}
