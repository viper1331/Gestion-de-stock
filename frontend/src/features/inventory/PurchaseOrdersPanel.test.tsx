import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom";

import { PurchaseOrdersPanel } from "./PurchaseOrdersPanel";
import { SpellcheckSettingsProvider } from "../../app/spellcheckSettings";

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
  },
  setAdminSiteOverride: vi.fn()
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
  beforeEach(() => {
    class ResizeObserverMock {
      observe() {}
      unobserve() {}
      disconnect() {}
    }

    vi.stubGlobal("ResizeObserver", ResizeObserverMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("opens the create modal without navigating to Not Found", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } }
    });

    render(
      <QueryClientProvider client={queryClient}>
        <SpellcheckSettingsProvider>
          <PurchaseOrdersPanel suppliers={[]} />
        </SpellcheckSettingsProvider>
      </QueryClientProvider>
    );

    fireEvent.click(
      await screen.findByRole("button", { name: /créer un bon de commande/i })
    );

    expect(screen.getByLabelText(/fournisseur/i)).toBeInTheDocument();
    expect(screen.queryByText(/not found/i)).not.toBeInTheDocument();
  });

  it("opens the create modal when crypto.randomUUID is unavailable", async () => {
    vi.stubGlobal("crypto", undefined);

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } }
    });

    render(
      <QueryClientProvider client={queryClient}>
        <SpellcheckSettingsProvider>
          <PurchaseOrdersPanel suppliers={[]} />
        </SpellcheckSettingsProvider>
      </QueryClientProvider>
    );

    fireEvent.click(
      await screen.findByRole("button", { name: /créer un bon de commande/i })
    );

    expect(screen.getByLabelText(/fournisseur/i)).toBeInTheDocument();
  });
});
