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
