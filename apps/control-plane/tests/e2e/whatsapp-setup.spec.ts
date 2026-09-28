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

test("a connected coexistence account identifies the number and safely returns human control", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("admin@example.test");
  await page.getByLabel("Password").fill("valid-admin");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/$/);

  await page.goto("/tenants/019c2000-0000-7000-8000-000000000102/whatsapp");
  await expect(
    page.getByRole("heading", { name: "+15550783881" }),
  ).toBeVisible();
  await expect(page.getByText("phone-123")).toBeVisible();
  await expect(page.getByText("Cliente ***0002")).toBeVisible();
  await expect(
    page.getByText("Contactos: solicitud aceptada por Meta"),
  ).toBeVisible();
  await expect(
    page.getByText(/no confirma que la sincronización haya terminado/i),
  ).toBeVisible();

  await page.getByText("Reactivar agente").click();
  await expect(
    page.getByText(/esta acción no envía una respuesta inmediata/i),
  ).toBeVisible();
  await page.getByRole("button", { name: "Confirmar reactivación" }).click();

  await expect(page).toHaveURL(/humanControl=resumed/);
  await expect(
    page.getByText(
      "El agente quedó habilitado para responder a futuros mensajes.",
    ),
  ).toBeVisible();
  await expect(page.getByText("Cliente ***0002")).toHaveCount(0);
});
