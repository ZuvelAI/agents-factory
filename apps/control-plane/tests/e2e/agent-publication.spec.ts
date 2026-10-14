import { expect, test } from "@playwright/test";

const tenant = "019c2000-0000-7000-8000-000000000102";
const account = "019c2000-0000-7000-8000-000000000202";
test("admin saves, prepares, reviews and explicitly publishes without reconnecting WhatsApp", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("admin@example.test");
  await page.getByLabel("Password").fill("valid-admin");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/$/);
  await page.goto(`/tenants/${tenant}/onboarding/agent`);
  await page
    .getByRole("textbox", { name: /^Saludo/ })
    .fill("Bienvenido a Zuvel, tu aliado digital.");
  await page
    .getByLabel("Instrucciones y alcance empresarial", { exact: false })
    .fill("Orienta sobre los servicios aprobados de Zuvel.");
  await page.getByRole("button", { name: "Guardar este paso" }).click();
  await expect(page.getByText("Paso guardado correctamente.")).toBeVisible();
  await page.goto(`/tenants/${tenant}/onboarding/test`);
  await page.getByRole("button", { name: "Preparar candidato" }).click();
  await page.getByRole("button", { name: "Ejecutar nuevas pruebas" }).click();
  await expect(
    page.getByText("Bienvenido a Zuvel, tu aliado digital.", { exact: true }),
  ).toBeVisible();
  await page.goto(`/tenants/${tenant}/onboarding/quality-gate`);
  await page.getByRole("link", { name: /Ver resultados guardados/ }).click();
  await expect(
    page.getByText("Bienvenido a Zuvel, tu aliado digital.", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("checkbox", { name: /Revisé todas las respuestas/ })
    .check();
  await page.getByRole("button", { name: "Aprobar revisión" }).click();
  await page.goto(`/tenants/${tenant}/onboarding/production`);
  await page.getByRole("link", { name: /Ver resultados guardados/ }).click();
  await page
    .getByLabel("Elige la cuenta de WhatsApp", { exact: false })
    .selectOption(account);
  await page
    .getByRole("checkbox", { name: /Confirmo publicar esta versión/ })
    .check();
  await page
    .getByRole("button", { name: "Publicar versión en WhatsApp" })
    .click();
  await expect(
    page.getByText(/^Cuenta 15550783881: versión activa/),
  ).toBeVisible();
  await page.goto(`/tenants/${tenant}/onboarding/agent`);
  await page
    .getByRole("textbox", { name: /^Saludo/ })
    .fill("Borrador nuevo sin publicar");
  await page.getByRole("button", { name: "Guardar este paso" }).click();
  await page.goto(`/tenants/${tenant}/onboarding/whatsapp`);
  await expect(page.getByText(/No necesitas reconectar/)).toBeVisible();
  await expect(
    page.getByText(/^Cuenta 15550783881: versión activa/),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Connect with Meta" }),
  ).toHaveCount(0);
});
