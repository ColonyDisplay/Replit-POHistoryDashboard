import { expect, test } from "@playwright/test";
import {
  KPI_DETAIL,
  KPI_HEALTH,
  KPI_SUMMARY,
  KPI_TRENDS,
} from "./fixtures/kpi-fixtures.mjs";

async function installDeterministicRoutes(page) {
  await page.route("https://fonts.googleapis.com/**", async (route) => {
    await route.fulfill({
      body: "/* Remote fonts are disabled for deterministic screenshots. */",
      contentType: "text/css",
      status: 200,
    });
  });

  await page.route("**/api/**", async (route) => {
    const { pathname } = new URL(route.request().url());
    if (pathname === "/api/kpis") {
      await route.fulfill({ json: KPI_SUMMARY });
      return;
    }
    if (pathname === "/api/kpis/trends") {
      await route.fulfill({ json: KPI_TRENDS });
      return;
    }
    if (/^\/api\/kpis\/[A-Z0-9-]+\/detail$/.test(pathname)) {
      await route.fulfill({ json: KPI_DETAIL });
      return;
    }
    if (pathname === "/api/health") {
      await route.fulfill({ json: KPI_HEALTH });
      return;
    }
    await route.continue();
  });
}

async function settlePage(page) {
  await page.evaluate(async () => {
    await document.fonts.ready;
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  });
}

async function openHome(page) {
  await page.goto("/");
  await expect(page.locator(".dashboard-choice-grid")).toBeVisible();
  await settlePage(page);
}

async function openOperationsKpi(page) {
  await openHome(page);
  await page.getByRole("button", { name: /^Operations KPI/ }).click();
  await expect(page.getByRole("heading", { name: "Operational performance" })).toBeVisible();
  await expect(page.locator(".kpi-metric-card").first()).toBeVisible();
  await expect(page.locator(".kpi-card-spark").first()).toBeVisible();
  await settlePage(page);
}

async function openAdminProfileMenu(page) {
  await openHome(page);
  await page.locator(".preview-admin-menu > summary").click();
  const adminLink = page.locator(".preview-admin-popover").getByRole("link", { name: /^Admin/ });
  await expect(adminLink).toBeVisible();
  return adminLink;
}

async function mockMember(page, sections) {
  await page.route("**/me", async (route) => {
    await route.fulfill({
      json: {
        access: true,
        email: "member@colonydisplay.com",
        name: "Portal Member",
        role: "viewer",
        sections,
        previewMode: false,
        liveData: false,
      },
    });
  });
}

test.beforeEach(async ({ page }) => {
  await installDeterministicRoutes(page);
});

test("Home preserves the compact industrial dashboard", async ({ page }) => {
  await openHome(page);

  await expect(page.locator(".dashboard-choice-card")).toHaveCount(3);
  const firstCardBox = await page.locator(".dashboard-choice-card").first().boundingBox();
  expect(firstCardBox).not.toBeNull();
  expect(Math.abs(firstCardBox.width - firstCardBox.height)).toBeLessThanOrEqual(2);
  await expect(page.getByRole("button", { name: /^Users & access/ })).toHaveCount(0);
  await expect(page.locator("body")).toHaveCSS("background-color", "rgb(9, 12, 19)");
  await expect(page).toHaveScreenshot("home.png", { fullPage: true });
});

test("Member home balances two square dashboard choices", async ({ page }) => {
  await mockMember(page, ["search", "bom", "inventory", "operations_kpi"]);
  await openHome(page);

  const grid = page.locator(".dashboard-choice-grid");
  const cards = grid.locator(".dashboard-choice-card");
  await expect(grid).toHaveAttribute("data-card-count", "2");
  await expect(cards).toHaveCount(2);

  const [gridBox, firstCardBox] = await Promise.all([
    grid.boundingBox(),
    cards.first().boundingBox(),
  ]);
  expect(gridBox).not.toBeNull();
  expect(firstCardBox).not.toBeNull();
  expect(Math.abs(firstCardBox.width - firstCardBox.height)).toBeLessThanOrEqual(2);

  const viewport = page.viewportSize();
  expect(viewport).not.toBeNull();
  expect(Math.abs(gridBox.x - (viewport.width - gridBox.width) / 2)).toBeLessThanOrEqual(2);
  await expect(page).toHaveScreenshot("home-member-two-cards.png", { fullPage: true });
});

test("Operations KPI preserves four desktop columns and one mobile column", async (
  { page },
  testInfo,
) => {
  await openOperationsKpi(page);

  const firstGrid = page.locator(".kpi-summary-group").first().locator(".kpi-metric-grid");
  const columnCount = await firstGrid.evaluate((element) => (
    getComputedStyle(element).gridTemplateColumns.split(" ").filter(Boolean).length
  ));
  expect(columnCount).toBe(testInfo.project.name === "mobile" ? 1 : 4);
  await expect(firstGrid.locator(".kpi-metric-card")).toHaveCount(4);
  await expect(page).toHaveScreenshot("operations-kpi.png", { fullPage: true });
});

test("KPI detail preserves trend charts and published rows", async ({ page }) => {
  await openOperationsKpi(page);

  await page.getByRole("button", { name: /^Units shipped/ }).first().click();
  const detail = page.getByRole("dialog", { name: "Units shipped published detail" });
  await expect(detail).toBeVisible();
  await expect(detail.locator(".kpi-chart")).toHaveCount(2);
  await expect(detail.locator("tbody tr")).toHaveCount(3);
  await settlePage(page);
  await expect(page).toHaveScreenshot("kpi-detail.png", { fullPage: true });
});

test("PO History preserves the responsive search and results surface", async ({ page }) => {
  await openHome(page);

  await page.getByRole("button", { name: /^PO History/ }).click();
  await expect(page.getByPlaceholder(/vendor/)).toBeVisible();
  await expect(page.locator(".ag-root-wrapper")).toBeVisible();
  await expect(page.getByRole("button", { name: "Users" })).toHaveCount(0);
  await settlePage(page);
  await expect(page).toHaveScreenshot("po-history.png", { fullPage: true });
});

test("DataLake preserves the dark report grid", async ({ page }) => {
  await openHome(page);

  await page.getByRole("button", { name: /^DataLake/ }).click();
  await page.waitForURL("**/datalake");
  await expect(page.getByRole("heading", { name: "DataLake", level: 2 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Live DataLake reports are paused" })).toBeVisible();
  await expect(page.locator(".lake-json")).toHaveCount(0);
  await settlePage(page);
  await expect(page).toHaveScreenshot("datalake.png", { fullPage: true });
});

test("Admin provides a dedicated responsive users area", async ({ page }) => {
  const adminLink = await openAdminProfileMenu(page);
  await settlePage(page);
  await expect(page).toHaveScreenshot("admin-profile-menu.png", { fullPage: true });
  await adminLink.click();
  await page.waitForURL("**/admin");
  await expect(page.locator(".admin-section-sidebar").getByRole("heading", { name: "Admin" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Admin pages" })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Users & access/ })).toHaveAttribute("aria-current", "page");
  await expect(page.locator(".admin-section-content").getByRole("heading", { name: "Users & access" })).toBeVisible();
  await expect(page.locator(".users-page tbody tr").first()).toBeVisible();
  const addUserPanel = page.getByRole("region", { name: "Add user" });
  await expect(addUserPanel.getByRole("combobox", { name: "Role" })).toHaveValue("viewer");
  await expect(page.getByText("Admin-only capabilities").first()).toBeVisible();
  await expect(page.getByText("DataLake reports").first()).toBeVisible();
  await settlePage(page);
  await expect(page).toHaveScreenshot("admin.png", { fullPage: true });
});

test("Admin rejects direct visits without the users capability", async ({ page }) => {
  let usersRequested = false;
  await mockMember(page, ["search", "bom", "inventory", "operations_kpi"]);
  await page.route("**/users", async (route) => {
    usersRequested = true;
    await route.fulfill({ json: [] });
  });

  await page.goto("/admin");

  await expect(page.getByRole("heading", { name: "Admin access is restricted" })).toBeVisible();
  await expect(page.locator(".admin-section")).toHaveCount(0);
  expect(usersRequested).toBe(false);
});