import { render, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi, afterEach } from "vitest";

import { useIdleLogout } from "./useIdleLogout";

const logoutMock = vi.fn();

vi.mock("../features/auth/useAuth", () => ({
  useAuth: () => ({
    user: { id: 1, role: "user" },
    logout: logoutMock
  })
}));

const fetchPublicSystemConfigMock = vi.fn().mockResolvedValue({ idle_logout_minutes: 1 });

vi.mock("../lib/systemConfig", () => ({
  fetchPublicSystemConfig: () => fetchPublicSystemConfigMock()
}));

function TestHarness() {
  useIdleLogout();
  return null;
}

describe("useIdleLogout", () => {
  afterEach(() => {
    vi.useRealTimers();
    logoutMock.mockClear();
    fetchPublicSystemConfigMock.mockClear();
    window.localStorage.clear();
  });

  it("déconnecte après inactivité selon la configuration", async () => {
    vi.useFakeTimers();
    const queryClient = new QueryClient();

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/app"]}>
          <TestHarness />
        </MemoryRouter>
      </QueryClientProvider>
    );

    await waitFor(() => {
      expect(fetchPublicSystemConfigMock).toHaveBeenCalled();
    });

    vi.advanceTimersByTime(65_000);

    await waitFor(() => {
      expect(logoutMock).toHaveBeenCalledWith({ reason: "idle" });
    });
  });
});
