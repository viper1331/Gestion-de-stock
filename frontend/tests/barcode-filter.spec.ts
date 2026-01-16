import { expect, test } from "@playwright/test";

test.describe("Barcode module filter", () => {
  test("vehicle inventory is excluded from module options", async ({ page }) => {
    await page.goto("/barcode", { waitUntil: "networkidle" });

    const moduleSelect = page.getByLabel("Module");
    if (await moduleSelect.count()) {
      await expect(moduleSelect.locator('option[value="vehicle_inventory"]')).toHaveCount(0);
      await expect(moduleSelect.locator('option[value="pharmacy"]')).toHaveCount(1);
    }
  });
});
