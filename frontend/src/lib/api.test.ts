import { describe, expect, it, vi, beforeEach } from "vitest";

const emitAuthLogoutMock = vi.fn();
const getStoredRefreshTokenMock = vi.fn();
const getRefreshTokenStorageMock = vi.fn();
const clearStoredRefreshTokenMock = vi.fn();

vi.mock("../features/auth/authEvents", () => ({
  emitAuthLogout: (reason: string) => emitAuthLogoutMock(reason)
}));

vi.mock("../features/auth/authStorage", () => ({
  getStoredRefreshToken: () => getStoredRefreshTokenMock(),
  getRefreshTokenStorage: () => getRefreshTokenStorageMock(),
  clearStoredRefreshToken: () => clearStoredRefreshTokenMock(),
  storeRefreshToken: vi.fn()
}));

import { handleApiError } from "./api";

describe("api interceptor", () => {
  beforeEach(() => {
    emitAuthLogoutMock.mockClear();
    getStoredRefreshTokenMock.mockReset();
    getRefreshTokenStorageMock.mockReset();
    clearStoredRefreshTokenMock.mockClear();
  });

  it("déclenche un logout silencieux sur 401", async () => {
    getStoredRefreshTokenMock.mockReturnValue(null);
    getRefreshTokenStorageMock.mockReturnValue(null);

    const error = {
      config: {},
      response: { status: 401 },
      message: "Unauthorized"
    };

    await expect(handleApiError(error)).rejects.toBe(error);

    expect(clearStoredRefreshTokenMock).toHaveBeenCalled();
    expect(emitAuthLogoutMock).toHaveBeenCalledWith("unauthorized");
  });
});
