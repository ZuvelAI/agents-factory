import { expect, test } from "@playwright/test";

test("a platform admin reviews and closes an ambiguous WhatsApp alert", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("admin@example.test");
  await page.getByLabel("Password").fill("valid-admin");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/$/);

  await page.goto("/operations");
  await expect(
    page.getByRole("heading", { name: "1 alerta pendiente" }),
  ).toBeVisible();
  await expect(page.getByText("waba-ambiguous")).toBeVisible();
  await page.getByText("Registrar revisión y cerrar").click();
  await page
    .getByLabel("Nota de revisión")
    .fill("Verificado manualmente en Meta");
  await page.getByRole("button", { name: "Confirmar cierre" }).click();

  await expect(page).toHaveURL(/alertResolution=resolved/);
  await expect(
    page.getByRole("heading", { name: "0 alertas pendientes" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Historial de alertas" }).click();
  await expect(page.getByText("Verificado manualmente en Meta")).toBeVisible();
  await expect(
    page.getByText("019c2000-0000-7000-8000-000000000111"),
  ).toBeVisible();
});
