import { expect, test } from "@playwright/test";

const routes = [
  "/inventory",
  "/purchase-orders",
  "/dotations",
  "/collaborators",
  "/pharmacy",
  "/pdf-config"
];

const viewports = [
  { name: "lg", width: 1440, height: 900 },
  { name: "md", width: 1024, height: 900 },
  { name: "sm", width: 390, height: 844 }
];

test.describe("Editable layouts are responsive", () => {
  for (const viewport of viewports) {
    test(`no horizontal overflow at ${viewport.name}`, async ({ page }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });

      for (const route of routes) {
        await page.goto(route, { waitUntil: "networkidle" });
        await page.waitForTimeout(500);

        const hasOverflow = await page.evaluate(() =>
          document.documentElement.scrollWidth > document.documentElement.clientWidth + 1
        );

        expect(hasOverflow, `Overflow detected on ${route} at ${viewport.name}`).toBeFalsy();

        await page.screenshot({
          path: `test-results/layout-${route.replaceAll("/", "-")}-${viewport.name}.png`,
          fullPage: true
        });
      }
    });
  }
});

test.describe("Mobile navigation drawer", () => {
  test("opens configuration PDF from the drawer", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/inventory", { waitUntil: "networkidle" });

    await page.getByRole("button", { name: /ouvrir le menu principal/i }).click();

    const administrationButton = page.getByRole("button", { name: /administration/i });
    await administrationButton.click();

    const pdfLink = page.getByRole("link", { name: "Configuration PDF" });
    await expect(pdfLink).toBeVisible();
    await expect(pdfLink).toBeInViewport();

    await pdfLink.click();
    await expect(page).toHaveURL(/\/pdf-config/);
  });
});
