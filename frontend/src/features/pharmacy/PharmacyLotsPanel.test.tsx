import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import { PharmacyLotsPanel } from "./PharmacyLotsPanel";
import { SpellcheckSettingsProvider } from "../../app/spellcheckSettings";

vi.mock("../../lib/api", () => ({
  api: {
    get: vi.fn(async (url: string) => {
      if (url.includes("/pharmacy/lots")) {
        return { data: [] };
      }
      if (url.includes("/admin/custom-fields")) {
        return { data: [] };
      }
      if (url.includes("/pharmacy/")) {
        return { data: [] };
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

describe("PharmacyLotsPanel", () => {
  it("opens the create lot modal from the Nouveau lot button", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } }
    });

    render(
      <QueryClientProvider client={queryClient}>
        <SpellcheckSettingsProvider>
          <PharmacyLotsPanel canEdit />
        </SpellcheckSettingsProvider>
      </QueryClientProvider>
    );

    fireEvent.click(await screen.findByRole("button", { name: /nouveau lot/i }));

    expect(screen.getByRole("heading", { name: /créer un lot/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/nom/i)).toBeInTheDocument();
  });
});
