import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom";

import { PurchaseOrdersPanel } from "./PurchaseOrdersPanel";

vi.mock("../../lib/api", () => ({
  api: {
    get: vi.fn(async (url: string) => {
      if (url.includes("/dotations/assignees")) {
        return { data: { assignees: [] } };
      }
      return { data: [] };
    }),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn()
  }
}));

vi.mock("../auth/useAuth", () => ({
  useAuth: () => ({
    user: { role: "admin" }
  })
}));

vi.mock("../permissions/useModulePermissions", () => ({
  useModulePermissions: () => ({
    canAccess: () => true,
    isLoading: false,
    data: []
  })
}));

describe("PurchaseOrdersPanel", () => {
  it("opens the create modal without navigating to Not Found", async () => {
    if (!globalThis.crypto?.randomUUID) {
      Object.defineProperty(globalThis, "crypto", {
        value: { randomUUID: () => "test-uuid" }
      });
    }

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } }
    });

    render(
      <QueryClientProvider client={queryClient}>
        <PurchaseOrdersPanel suppliers={[]} />
      </QueryClientProvider>
    );

    fireEvent.click(
      await screen.findByRole("button", { name: /créer un bon de commande/i })
    );

    expect(screen.getByLabelText(/fournisseur/i)).toBeInTheDocument();
    expect(screen.queryByText(/not found/i)).not.toBeInTheDocument();
  });
});
