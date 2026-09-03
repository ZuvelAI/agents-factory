import { expect, test } from "@playwright/test";

test("dashboard answers operational questions across desktop and mobile", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("admin@example.test");
  await page.getByLabel("Password").fill("valid-admin");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(
    page.getByRole("heading", { name: "Operational dashboard" }),
  ).toBeVisible();
  await expect(page.getByText("3 / 4")).toBeVisible();
  await expect(page.getByText("2", { exact: true })).toBeVisible();
  await expect(page.getByText("1", { exact: true })).toBeVisible();
  await expect(page.getByText("3 / 5")).toBeVisible();
  await expect(page.getByText("$12.34")).toBeVisible();
  await expect(
    page.getByText(/7 usage events have unknown cost/),
  ).toBeVisible();
  await expect(page.getByText(/more than 24 hours old/)).toBeVisible();

  const casesCard = page.locator("article", {
    hasText: "Critical cases overdue",
  });
  await expect(
    casesCard.getByRole("link", { name: "Needs attention" }),
  ).toHaveAttribute("href", "/cases?priority=CRITICAL&target=overdue");
  const integrationCard = page.locator("article", {
    hasText: "Integration health",
  });
  await expect(
    integrationCard.getByRole("link", { name: "Unknown" }),
  ).toHaveAttribute("href", "/integrations?health=needs-attention");

  await page.setViewportSize({ width: 390, height: 844 });
  const menu = page.getByRole("button", { name: "Menu" });
  await expect(menu).toBeVisible();
  await menu.focus();
  await page.keyboard.press("Enter");
  await expect(menu).toHaveAttribute("aria-expanded", "true");
  const mobileNavigation = page.getByRole("navigation", {
    name: "Mobile Control Plane",
  });
  await expect(
    mobileNavigation.getByRole("link", { name: "Usage & Costs" }),
  ).toBeVisible();
  await expect(
    mobileNavigation.getByRole("link", { name: "Dashboard" }),
  ).toHaveAttribute("aria-current", "page");
});
