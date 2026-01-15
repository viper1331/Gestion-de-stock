import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ColumnManager } from "./ColumnManager";
import { SpellcheckSettingsProvider } from "../app/spellcheckSettings";

describe("ColumnManager", () => {
  it("renders column options when opened", () => {
    const options = [
      { key: "name", label: "Nom" },
      { key: "sku", label: "SKU" }
    ];
    const visibility = { name: true, sku: false };

    render(
      <SpellcheckSettingsProvider>
        <ColumnManager
          options={options}
          visibility={visibility}
          onToggle={() => {}}
          description="Choisissez les colonnes."
        />
      </SpellcheckSettingsProvider>
    );

    fireEvent.click(screen.getByRole("button", { name: /colonnes/i }));

    expect(screen.getByText("Nom")).toBeInTheDocument();
    expect(screen.getByText("SKU")).toBeInTheDocument();
  });
});
