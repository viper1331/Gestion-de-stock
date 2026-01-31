import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { describe, expect, it } from "vitest";

import { LibraryLotCardImage } from "./VehicleInventoryPage";

describe("VehicleInventoryPage LibraryLotCardImage", () => {
  it("utilise cover_image_url en priorité", () => {
    render(
      <LibraryLotCardImage
        lot={{
          name: "Lot catalogue",
          image_url: "/media/lot.png",
          cover_image_url: "/media/catalog.png"
        }}
        showCatalogBadge
      />
    );

    const image = screen.getByRole("img");
    expect(image).toHaveAttribute("src", expect.stringContaining("/media/catalog.png"));
  });

  it("affiche le placeholder sans image", () => {
    const { container } = render(
      <LibraryLotCardImage
        lot={{
          name: "Lot sans image",
          image_url: null,
          cover_image_url: null
        }}
      />
    );

    expect(container).toMatchSnapshot();
  });
});
