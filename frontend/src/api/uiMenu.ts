import { api } from "../lib/api";

type MenuOrderResponse = {
  menu_key: string;
  order: string[];
};

export async function getMenuOrder(menuKey = "main_modules"): Promise<string[]> {
  const response = await api.get<MenuOrderResponse>("/ui/menu-order", {
    params: { menu_key: menuKey }
  });
  return response.data.order;
}

export async function setMenuOrder(order: string[], menuKey = "main_modules"): Promise<string[]> {
  const response = await api.put<MenuOrderResponse>("/ui/menu-order", {
    menu_key: menuKey,
    order
  });
  return response.data.order;
}
