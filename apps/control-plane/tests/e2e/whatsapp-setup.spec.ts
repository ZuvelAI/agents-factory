import { expect, test } from "@playwright/test";

test("WhatsApp setup uses Embedded Signup without credential fields", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("admin@example.test");
  await page.getByLabel("Password").fill("valid-admin");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/$/);

  await page.goto("/tenants/019c2000-0000-7000-8000-000000000101/whatsapp");
  await expect(
    page.getByRole("heading", { name: "WhatsApp setup" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Connect with Meta" }),
  ).toBeVisible();
  await expect(
    page.getByText(/never asks for or displays access tokens/i),
  ).toBeVisible();
  await expect(page.locator('input[type="password"]')).toHaveCount(0);
  await expect(page.getByText(/Not connected/)).toBeVisible();
});
