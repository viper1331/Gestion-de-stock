import { describe, expect, it } from "vitest";

import {
  buildGeneralInventoryByZone,
  DEFAULT_VIEW_LABEL,
  getVehicleViews,
  normalizeVehicleViewsInput,
  normalizeViewName,
  resolvePinnedView
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

  it("retourne null si aucune vue épinglée n'est définie", () => {
    expect(resolvePinnedView(["CABINE", "COFFRE"], null)).toBeNull();
  });

  it("retourne null si la vue épinglée n'existe plus", () => {
    expect(resolvePinnedView(["CABINE", "COFFRE"], "SOUTE")).toBeNull();
  });


  it("construit l'inventaire général en regroupant les sous-vues vers la zone principale", () => {
    const zones = buildGeneralInventoryByZone({
      views: ["CABINE", "CABINE - SIEGE", "COFFRE DROIT"],
      items: [
        {
          id: 1,
          name: "Lampe",
          sku: "L-1",
          category_id: 10,
          size: null,
          target_view: "CABINE - SIEGE",
          quantity: 2,
          remise_item_id: 101,
          pharmacy_item_id: null,
          remise_quantity: null,
          pharmacy_quantity: null,
          image_url: null,
          position_x: null,
          position_y: null,
          lot_id: null,
          lot_name: null,
          show_in_qr: true,
          vehicle_type: null
        },
        {
          id: 2,
          name: "Lampe",
          sku: "L-1",
          category_id: 10,
          size: null,
          target_view: "CABINE",
          quantity: 1,
          remise_item_id: 101,
          pharmacy_item_id: null,
          remise_quantity: null,
          pharmacy_quantity: null,
          image_url: null,
          position_x: null,
          position_y: null,
          lot_id: null,
          lot_name: null,
          show_in_qr: true,
          vehicle_type: null
        },
        {
          id: 3,
          name: "Extincteur 2kg",
          sku: "E-2",
          category_id: 10,
          size: null,
          target_view: "COFFRE DROIT",
          quantity: 1,
          remise_item_id: 202,
          pharmacy_item_id: null,
          remise_quantity: null,
          pharmacy_quantity: null,
          image_url: null,
          position_x: null,
          position_y: null,
          lot_id: null,
          lot_name: null,
          show_in_qr: true,
          vehicle_type: null
        }
      ]
    });

    expect(zones).toEqual([
      {
        zoneId: "CABINE",
        zoneLabel: "CABINE",
        items: [{ id: "1", label: "Lampe", qty: 3 }]
      },
      {
        zoneId: "COFFRE DROIT",
        zoneLabel: "COFFRE DROIT",
        items: [{ id: "3", label: "Extincteur 2kg", qty: 1 }]
      }
    ]);
  });

});
