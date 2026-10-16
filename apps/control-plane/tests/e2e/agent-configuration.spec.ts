import { expect, test } from "@playwright/test";
const tenant = "019c2000-0000-7000-8000-000000000102";
const first = "019c2000-0000-7000-8000-000000000501";
const second = "019c2000-0000-7000-8000-000000000502";
const edit = (agent: string) => `/tenants/${tenant}/agents/${agent}/edit`;
test("required choices cannot be cleared while optional policies can remain pending", async ({
  page,
}) => {
  await page.goto(edit(first));
  for (const label of [
    /^Modelo del borrador/,
    /^Tono/,
    /^He revisado este contenido exacto/,
  ]) {
    const control = page.getByLabel(label);
    await expect(control).toHaveCount(1);
    await expect(control.locator('option[value=""]')).toHaveCount(0);
  }
  await page.getByText("Políticas y operación", { exact: true }).click();
  const pricing = page.getByLabel(/^Respuesta sobre precios/);
  await expect(pricing.locator('option[value=""]')).toHaveCount(1);
  await pricing.selectOption("");
  await page
    .getByRole("button", { name: "Guardar borrador", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("Borrador guardado");
  await page.reload();
  await expect(pricing).toHaveValue("");
});
test("company fields are protected until the save response arrives", async ({
  page,
}) => {
  await page.goto(`/tenants/${tenant}/settings`);
  const description = page.getByLabel("Descripción de la empresa");
  await description.fill("guardado-empresa-lento");
  await page
    .getByRole("button", { name: "Guardar información empresarial" })
    .click();
  await expect(description).toBeDisabled();
  await expect(page.getByRole("status")).toContainText(
    "Datos compartidos guardados",
  );
  await expect(description).toBeEnabled();
});
test("multiline language input preserves a typed newline and saves two languages", async ({
  page,
}) => {
  await page.goto(edit(first));
  const languages = page.getByLabel("Idiomas (es-CO o en-US, uno por línea)");
  await languages.fill("es-CO");
  await languages.press("End");
  await languages.press("Enter");
  await languages.pressSequentially("en-US");
  await expect(languages).toHaveValue("es-CO\nen-US");
  await page
    .getByRole("button", { name: "Guardar borrador", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("Borrador guardado");
  await page.reload();
  await expect(languages).toHaveValue("es-CO\nen-US");
});
test("fields are protected while a save is in flight", async ({ page }) => {
  await page.goto(edit(first));
  const instructions = page.getByLabel("Instrucciones del agente");
  await instructions.fill("guardado-lento-controlado");
  await page
    .getByRole("button", { name: "Guardar borrador", exact: true })
    .click();
  await expect(instructions).toBeDisabled();
  await expect(page.getByRole("status")).toContainText("Borrador guardado");
  await expect(instructions).toBeEnabled();
});
test("company edits are not silently discarded by navigating away", async ({
  page,
}) => {
  await page.goto(`/tenants/${tenant}/settings`);
  await page
    .getByLabel("Descripción de la empresa")
    .fill("Texto empresarial sin guardar");
  let prompted = false;
  page.on("dialog", (dialog) => {
    prompted = true;
    return dialog.dismiss();
  });
  await page.getByRole("link", { name: "← Empresa", exact: true }).click();
  await expect.poll(() => prompted).toBe(true);
  await expect(page).toHaveURL(`/tenants/${tenant}/settings`);
  await expect(page.getByLabel("Descripción de la empresa")).toHaveValue(
    "Texto empresarial sin guardar",
  );
});
test("browser Back asks before discarding company edits", async ({ page }) => {
  await page.goto(`/tenants/${tenant}`);
  await page
    .getByRole("link", { name: "Información empresarial", exact: true })
    .click();
  await page
    .getByLabel("Descripción de la empresa")
    .fill("Texto protegido al volver");
  let prompted = false;
  page.on("dialog", (dialog) => {
    prompted = true;
    return dialog.dismiss();
  });
  await page.evaluate(() => history.back());
  await expect.poll(() => prompted).toBe(true);
  await expect(page).toHaveURL(`/tenants/${tenant}/settings`);
  await expect(page.getByLabel("Descripción de la empresa")).toHaveValue(
    "Texto protegido al volver",
  );
});
test("company changes require explicit incorporation into the agent draft", async ({
  page,
}) => {
  await page.goto(`/tenants/${tenant}/settings`);
  await page
    .getByLabel("Descripción de la empresa")
    .fill("Información compartida actualizada");
  await page
    .getByRole("button", { name: "Guardar información empresarial" })
    .click();
  await expect(page.getByRole("status")).toContainText(
    "Datos compartidos guardados",
  );
  await page.goto(edit(first));
  await expect(
    page.getByText(/Hay una actualización disponible/),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Comparar actualización de empresa" })
    .click();
  await expect(
    page.getByText("Datos compartidos actuales", { exact: true }),
  ).toBeVisible();
  await page.getByRole("checkbox").check();
  await page
    .getByRole("button", { name: "Incorporar información", exact: true })
    .click();
  await expect(
    page.getByText("Datos de empresa incorporados al borrador.", {
      exact: true,
    }),
  ).toBeVisible();
});
test.beforeEach(async ({ page, request }) => {
  await request.post("http://127.0.0.1:3132/__test/reset-configuration", {
    headers: {
      Authorization: `Bearer e30.${Buffer.from(JSON.stringify({ app_metadata: { platform_role: "platform_admin" } })).toString("base64url")}.test`,
    },
  });
  await page.goto("/login");
  await page.getByLabel("Email").fill("admin@example.test");
  await page.getByLabel("Password").fill("valid-admin");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/$/);
});
test("two agents save independently without changing the published overview", async ({
  page,
}) => {
  await page.goto(edit(first));
  await expect(
    page.getByRole("heading", { name: "Editar agente" }),
  ).toBeVisible();
  await page
    .getByLabel("Instrucciones del agente")
    .fill("Mi configuración comercial");
  await page
    .getByRole("button", { name: "Guardar borrador", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("Borrador guardado");
  await page.reload();
  await expect(page.getByLabel("Instrucciones del agente")).toHaveValue(
    "Mi configuración comercial",
  );
  await page.goto(edit(second));
  await expect(page.getByLabel("Instrucciones del agente")).toHaveValue(
    "Configuración de soporte",
  );
  await page.goto(`/tenants/${tenant}/agents/${first}`);
  await expect(
    page.getByText("Orienta sobre los servicios de Zuvel.", { exact: true }),
  ).toBeVisible();
});
test("conflict preserves text and requires explicit comparison", async ({
  page,
}) => {
  await page.goto(edit(first));
  await page
    .getByLabel("Instrucciones del agente")
    .fill("conflicto-controlado");
  await page
    .getByRole("button", { name: "Guardar borrador", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Hay otra revisión guardada" }),
  ).toBeVisible();
  await expect(page.getByLabel("Instrucciones del agente")).toHaveValue(
    "conflicto-controlado",
  );
  await page.getByRole("button", { name: "Recargar para comparar" }).click();
  await expect(page.getByText("Guardado: revisión 2")).toBeVisible();
  await expect(page.getByLabel("Instrucciones del agente")).toHaveValue(
    "conflicto-controlado",
  );
  await page
    .getByRole("button", {
      name: "Usar revisión guardada y descartar mi texto",
    })
    .click();
  await expect(page.getByLabel("Instrucciones del agente")).toHaveValue(
    "Cambio de otro administrador",
  );
});
test("editor fits mobile and presents supported model choices without publishing", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await page.goto(edit(first));
  await expect(
    page.getByRole("link", { name: "Probar y publicar" }),
  ).toHaveAttribute("href", `/tenants/${tenant}/agents/${first}/test`);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await page.setViewportSize({ width: 1440, height: 1050 });
  await page.screenshot({
    path: testInfo.outputPath("editor-agente.png"),
    fullPage: true,
  });
});
