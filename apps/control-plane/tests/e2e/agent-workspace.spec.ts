import { expect, test } from "@playwright/test";
const tenant = "019c2000-0000-7000-8000-000000000102";
test.beforeEach(async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("admin@example.test");
  await page.getByLabel("Password").fill("valid-admin");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/$/);
});
test("company cards retain identity, support zero/one/many agents and keyboard search", async ({
  page,
}) => {
  await page.goto("/tenants");
  await expect(
    page.getByRole("heading", { name: "Tus empresas" }),
  ).toBeVisible();
  await expect(page.locator(".company-card")).toHaveCount(3);
  await expect(page.getByText("2 agentes", { exact: true })).toBeVisible();
  await expect(page.getByText("1 agente", { exact: true })).toBeVisible();
  await expect(page.getByText("Sin agentes", { exact: true })).toBeVisible();
  const links = page.getByRole("link", { name: "Ver empresa" });
  expect(await links.nth(1).getAttribute("href")).not.toBe(
    await links.nth(2).getAttribute("href"),
  );
  await page.getByLabel("Buscar empresa").focus();
  await page.keyboard.type("Zuvel");
  await page.keyboard.press("Enter");
  await expect(page.locator(".company-card")).toHaveCount(1);
  await page.getByRole("link", { name: "Ver empresa" }).click();
  await expect(page).toHaveURL(`/tenants/${tenant}`);
  await expect(
    page.getByRole("heading", { name: "Zuvel", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Abrir agente" })).toHaveCount(2);
  await expect(
    page.getByRole("button", { name: "Nuevo agente" }),
  ).toBeDisabled();
});
test("backend failure is not reported as zero companies and retry works", async ({
  page,
}) => {
  await page.goto("/tenants?query=fallo-controlado");
  await expect(
    page.getByRole("heading", { name: "No pudimos cargar las empresas" }),
  ).toBeVisible();
  await expect(page.getByText("No hay empresas registradas")).toHaveCount(0);
  await page.getByRole("link", { name: "Volver a consultar" }).click();
  await expect(page.locator(".company-card")).toHaveCount(3);
});
test("workspace fits narrow and desktop viewports with long company names", async ({
  page,
}) => {
  for (const width of [390, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/tenants");
    await expect(
      page.getByRole("heading", { name: "Tus empresas" }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page.getByLabel("Buscar empresa").focus();
    await expect(page.getByLabel("Buscar empresa")).toBeFocused();
  }
});
