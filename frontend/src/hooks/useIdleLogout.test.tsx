import { render, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi, afterEach } from "vitest";

import { useIdleLogout } from "./useIdleLogout";
import { AUTH_LOGOUT_STORAGE_KEY, REFRESH_TOKEN_STORAGE_KEY } from "../features/auth/authStorage";

const logoutMock = vi.fn();
const logoutSilentMock = vi.fn();

vi.mock("@tanstack/react-query", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-query")>();
  return {
    ...actual,
    useQuery: () => ({
      data: { idle_logout_minutes: 1, logout_on_close: false }
    })
  };
});

vi.mock("../features/auth/useAuth", () => ({
  useAuth: () => ({
    user: { id: 1, role: "user" },
    logout: logoutMock,
    logoutSilent: logoutSilentMock
  })
}));

function TestHarness() {
  useIdleLogout();
  return null;
}

describe("useIdleLogout", () => {
  afterEach(() => {
    vi.useRealTimers();
    logoutMock.mockClear();
    logoutSilentMock.mockClear();
    window.localStorage.clear();
    window.sessionStorage.clear();
  });

  it("déconnecte après inactivité selon la configuration", async () => {
    let now = 0;
    const dateSpy = vi.spyOn(Date, "now").mockImplementation(() => now);
    vi.useFakeTimers({
      toFake: ["setInterval", "clearInterval", "setTimeout", "clearTimeout"]
    });
    const queryClient = new QueryClient();

    try {
      render(
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={["/app"]}>
            <TestHarness />
          </MemoryRouter>
        </QueryClientProvider>
      );

      now = 65_000;
      vi.advanceTimersByTime(65_000);

      expect(logoutMock).toHaveBeenCalledWith({ reason: "idle" });
    } finally {
      dateSpy.mockRestore();
    }
  });

  it("déconnecte les autres onglets si le token est supprimé", async () => {
    const queryClient = new QueryClient();

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/app"]}>
          <TestHarness />
        </MemoryRouter>
      </QueryClientProvider>
    );

    window.dispatchEvent(
      new StorageEvent("storage", {
        key: REFRESH_TOKEN_STORAGE_KEY,
        oldValue: "token",
        newValue: null
      })
    );

    await waitFor(() => {
      expect(logoutSilentMock).toHaveBeenCalled();
    });
  });

  it("réagit aux signaux de logout multi-onglets", async () => {
    const queryClient = new QueryClient();

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/app"]}>
          <TestHarness />
        </MemoryRouter>
      </QueryClientProvider>
    );

    window.dispatchEvent(
      new StorageEvent("storage", {
        key: AUTH_LOGOUT_STORAGE_KEY,
        oldValue: null,
        newValue: JSON.stringify({ ts: Date.now(), reason: null })
      })
    );

    await waitFor(() => {
      expect(logoutSilentMock).toHaveBeenCalled();
    });
  });
});
