import { describe, expect, it } from "vitest";

import {
  DEFAULT_VIEW_LABEL,
  getVehicleViews,
  normalizeVehicleViewsInput,
  normalizeViewName
} from "./VehicleInventoryPage";

describe("VehicleInventoryPage helpers", () => {
  it("normalise et déduplique les vues saisies", () => {
    const views = normalizeVehicleViewsInput(" Vue 1, vue-2\nVUE 1 ");

    expect(views).toEqual(["VUE 1", "VUE - 2"]);
  });

  it("retourne la vue par défaut lorsque l'entrée est vide", () => {
    expect(normalizeVehicleViewsInput(" \n , ")).toEqual([DEFAULT_VIEW_LABEL]);
  });

  it("nettoie les caractères spéciaux et les tirets", () => {
    expect(normalizeViewName("  dépôt-principal  ")).toBe("DEPOT - PRINCIPAL");
  });

  it("utilise les vues configurées du véhicule et supprime les doublons", () => {
    const vehicle = {
      id: 1,
      name: "Camion pompe",
      sizes: ["Vue principale", "Cabine"],
      image_url: null,
      vehicle_type: "incendie" as const,
      view_configs: [
        { name: "Cabine", background_photo_id: null, background_url: null },
        { name: "Arrivée-arrière", background_photo_id: null, background_url: null }
      ]
    };

    expect(getVehicleViews(vehicle)).toEqual(["CABINE", "ARRIVEE - ARRIERE"]);
  });

  it("retourne la vue par défaut quand aucun véhicule n'est sélectionné", () => {
    expect(getVehicleViews(null)).toEqual([DEFAULT_VIEW_LABEL]);
  });
});
