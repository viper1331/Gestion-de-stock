import { api } from "../lib/api";

export type MenuOrderItem = {
  id: string;
  parentId: string | null;
  order: number;
};

export type MenuOrderResponse = {
  menu_key: string;
  version: number;
  items: MenuOrderItem[];
};

export type MenuOrderPayload = {
  version: number;
  items: MenuOrderItem[];
};

export async function getMenuOrder(menuKey = "main_menu"): Promise<MenuOrderResponse | null> {
  const response = await api.get<MenuOrderResponse | null>("/ui/menu-order", {
    params: { menu_key: menuKey }
  });
  return response.data ?? null;
}

export async function setMenuOrder(
  payload: MenuOrderPayload,
  menuKey = "main_menu"
): Promise<MenuOrderResponse> {
  const response = await api.put<MenuOrderResponse>("/ui/menu-order", payload, {
    params: { menu_key: menuKey }
  });
  return response.data;
}
