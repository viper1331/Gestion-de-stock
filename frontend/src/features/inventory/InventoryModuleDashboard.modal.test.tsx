import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom";

import { InventoryModuleDashboard } from "./InventoryModuleDashboard";
import { SpellcheckSettingsProvider } from "../../app/spellcheckSettings";

vi.mock("../../lib/api", () => ({
  api: {
    get: vi.fn(async (url: string) => {
      if (url.includes("/items")) {
        return {
          data: [
            {
              id: 1,
              name: "Casque",
              sku: "HAB-001",
              category_id: null,
              size: null,
              quantity: 3,
              low_stock_threshold: 2,
              track_low_stock: true,
              supplier_id: null,
              expiration_date: null,
              remise_item_id: null,
              image_url: null
            }
          ]
        };
      }
      if (url.includes("/categories")) {
        return { data: [] };
      }
      if (url.includes("/suppliers")) {
        return { data: [] };
      }
      return { data: [] };
    })
  }
}));

vi.mock("../auth/useAuth", () => ({
  useAuth: () => ({
    user: { role: "admin" }
  })
}));

describe("InventoryModuleDashboard modal", () => {
  beforeAll(() => {
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: (query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn()
      })
    });

    if (!window.requestAnimationFrame) {
      window.requestAnimationFrame = (callback: FrameRequestCallback) => window.setTimeout(callback, 0);
    }

    if (!window.PointerEvent) {
      window.PointerEvent = window.MouseEvent as typeof window.PointerEvent;
    }

    if (!HTMLElement.prototype.setPointerCapture) {
      HTMLElement.prototype.setPointerCapture = () => {};
    }
  });

  beforeEach(() => {
    vi.clearAllMocks();
  });

  const renderDashboard = () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false }
      }
    });

    return render(
      <QueryClientProvider client={queryClient}>
        <SpellcheckSettingsProvider>
          <InventoryModuleDashboard
            config={{
              title: "Inventaire habillement",
              description: "Gestion des articles.",
              basePath: "/items",
              categoriesPath: "/categories",
              queryKeyPrefix: "inventory",
              storageKeyPrefix: "inventory",
              showPurchaseOrders: false
            }}
          />
        </SpellcheckSettingsProvider>
      </QueryClientProvider>
    );
  };

  it("opens the modal when clicking on Ajouter", async () => {
    renderDashboard();

    const addButton = await screen.findByRole("button", { name: /nouvel article/i });
    fireEvent.click(addButton);

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(within(dialog).getByText(/nouvel article/i)).toBeInTheDocument();
  });

  it("opens the modal when clicking on Modifier", async () => {
    renderDashboard();

    const editButton = await screen.findByRole("button", { name: /modifier/i });
    fireEvent.click(editButton);

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText(/modifier l'article/i)).toBeInTheDocument();
  });

  it("closes the modal on Escape", async () => {
    renderDashboard();

    const addButton = await screen.findByRole("button", { name: /nouvel article/i });
    fireEvent.click(addButton);
    await screen.findByRole("dialog");

    fireEvent.keyDown(window, { key: "Escape" });

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("drags the modal titlebar", async () => {
    renderDashboard();

    const addButton = await screen.findByRole("button", { name: /nouvel article/i });
    fireEvent.click(addButton);

    const dialog = await screen.findByRole("dialog");
    const titlebar = screen.getByTestId("modal-titlebar");

    vi.spyOn(dialog, "getBoundingClientRect").mockReturnValue({
      width: 600,
      height: 400,
      top: 0,
      left: 0,
      bottom: 0,
      right: 0,
      x: 0,
      y: 0,
      toJSON: () => ""
    });

    vi.spyOn(titlebar, "getBoundingClientRect").mockReturnValue({
      width: 600,
      height: 40,
      top: 0,
      left: 0,
      bottom: 40,
      right: 0,
      x: 0,
      y: 0,
      toJSON: () => ""
    });

    await waitFor(() => {
      expect(dialog.style.left).not.toBe("");
    });

    const previousLeft = dialog.style.left;
    const previousTop = dialog.style.top;

    fireEvent.pointerDown(titlebar, { clientX: 200, clientY: 200, button: 0, pointerId: 1 });
    await new Promise((resolve) => setTimeout(resolve, 0));
    fireEvent.pointerMove(window, { clientX: 260, clientY: 260, pointerId: 1 });
    fireEvent.pointerUp(window, { pointerId: 1 });

    await waitFor(() => {
      expect(dialog.style.left).not.toBe(previousLeft);
      expect(dialog.style.top).not.toBe(previousTop);
    });
  });
});
