import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MemoryRouter } from "react-router-dom";

import { Login } from "./Login";

vi.mock("./useAuth", () => ({
  useAuth: () => ({
    login: vi.fn().mockResolvedValue({ status: "authenticated" }),
    verifyTwoFactor: vi.fn(),
    verifyRecoveryCode: vi.fn(),
    clearError: vi.fn(),
    isLoading: false,
    error: null
  })
}));

describe("Login", () => {
  it("affiche le formulaire de connexion", () => {
    render(
      <MemoryRouter>
        <Login />
      </MemoryRouter>
    );

    expect(screen.getByText("Connexion")).toBeInTheDocument();
    expect(screen.getByLabelText("Identifiant")).toBeInTheDocument();
  });
});
