import { expect, test } from "@playwright/test";
const tenant = "019c2000-0000-7000-8000-000000000102";
const agent = "019c2000-0000-7000-8000-000000000501";
const path = `/tenants/${tenant}/agents/${agent}/test`;
test.beforeEach(async ({ page, request }) => {
  await request.post("http://127.0.0.1:3132/__workspace-publication/reset", {
    headers: {
      Authorization:
        "Bearer " +
        Buffer.from("{}").toString("base64url") +
        "." +
        Buffer.from(
          JSON.stringify({ app_metadata: { platform_role: "platform_admin" } }),
        ).toString("base64url") +
        ".test",
    },
  });
  await page.goto("/login");
  await request.post("http://127.0.0.1:3132/__test/reset-configuration", {
    headers: {
      Authorization: `Bearer e30.${Buffer.from(JSON.stringify({ app_metadata: { platform_role: "platform_admin" } })).toString("base64url")}.test`,
    },
  });
  await page.getByLabel("Email").fill("admin@example.test");
  await page.getByLabel("Password").fill("valid-admin");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/$/);
});
test("saved candidate preview and explicit publication do not auto-select an account", async ({
  page,
}) => {
  await page.goto(path);
  await expect(
    page.getByRole("heading", { name: "Probar y publicar" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Preparar versión de prueba" })
    .click();
  await page.getByLabel("Versión para probar").selectOption({ index: 1 });
  await page.getByLabel("Mensaje de prueba").fill("¿Qué servicios ofrecen?");
  await page.getByRole("button", { name: "Enviar prueba aislada" }).click();
  await expect(page.getByLabel("Mensajes de la prueba")).toContainText(
    "Respuesta simulada de Zuvel",
  );
  await page.getByRole("button", { name: "Ejecutar escenarios" }).click();
  await page.getByLabel("He revisado las respuestas exactas").check();
  await page.getByRole("button", { name: "Aprobar escenarios" }).click();
  await expect(
    page.getByRole("combobox", { name: /^Número destino/ }),
  ).toHaveValue("");
  await expect(
    page.getByRole("button", { name: "Publicar en este número" }),
  ).toBeDisabled();
  await page
    .getByRole("combobox", { name: /^Número destino/ })
    .selectOption({ index: 1 });
  await page.getByLabel("Confirmo la versión y el número destino").check();
  await page.getByRole("button", { name: "Publicar en este número" }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "Publicación confirmada" }),
  ).toContainText("Publicación confirmada");
});

test("preview conflicts preserve text and switching agents never shares candidates", async ({
  page,
}) => {
  await page.goto(path);
  await page
    .getByRole("button", { name: "Preparar versión de prueba" })
    .click();
  await page.getByLabel("Versión para probar").selectOption({ index: 1 });
  await page.getByLabel("Mensaje de prueba").fill("conflicto-controlado");
  await page.getByRole("button", { name: "Enviar prueba aislada" }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Tu texto se conserva" }),
  ).toBeVisible();
  await expect(page.getByLabel("Mensaje de prueba")).toHaveValue(
    "conflicto-controlado",
  );
  page.on("dialog", (dialog) => dialog.accept());
  await page.goto(path.replace(agent, "019c2000-0000-7000-8000-000000000502"));
  await expect(
    page.getByLabel("Versión para probar").locator("option"),
  ).toHaveCount(1);
});

test("editing after tests makes their approval unavailable", async ({
  page,
  context,
}) => {
  await page.goto(path);
  await page
    .getByRole("button", { name: "Preparar versión de prueba" })
    .click();
  await page.getByLabel("Versión para probar").selectOption({ index: 1 });
  await page.getByRole("button", { name: "Ejecutar escenarios" }).click();
  const editor = await context.newPage();
  await editor.goto(path.replace(/test$/, "edit"));
  await editor
    .getByLabel("Instrucciones del agente")
    .fill("Configuración actualizada después de las pruebas");
  await editor
    .getByRole("button", { name: "Guardar borrador", exact: true })
    .click();
  await expect(editor.getByRole("status")).toContainText("Borrador guardado");
  await page.getByRole("button", { name: "Consultar estado" }).click();
  await expect(
    page.getByText("Prueba obsoleta o vencida; prepara nuevas pruebas"),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Aprobar escenarios" }),
  ).toBeDisabled();
});

test("changing candidates asks before discarding an unsent preview", async ({
  page,
}) => {
  await page.goto(path);
  await page
    .getByRole("button", { name: "Preparar versión de prueba" })
    .click();
  const selection = page.getByLabel("Versión para probar");
  await selection.selectOption({ index: 1 });
  const candidate = await selection.inputValue();
  await page.getByLabel("Mensaje de prueba").fill("Texto todavía sin enviar");
  let asked = false;
  page.once("dialog", async (dialog) => {
    asked = true;
    await dialog.dismiss();
  });
  await selection.selectOption("");
  expect(asked).toBe(true);
  await expect(selection).toHaveValue(candidate);
  await expect(page.getByLabel("Mensaje de prueba")).toHaveValue(
    "Texto todavía sin enviar",
  );
});

test("testing panel fits mobile and desktop", async ({ page }, testInfo) => {
  await page.goto(path);
  await page
    .getByRole("button", { name: "Preparar versión de prueba" })
    .click();
  await page.getByLabel("Versión para probar").selectOption({ index: 1 });
  await page.setViewportSize({ width: 390, height: 900 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await page.setViewportSize({ width: 1440, height: 1050 });
  await page.screenshot({
    path: testInfo.outputPath("pruebas-agente.png"),
    fullPage: true,
  });
});

test("published legacy versions can be recovered without preparing a workspace candidate", async ({
  page,
  request,
}) => {
  await page.goto(path);
  await page
    .getByRole("button", { name: "Preparar versión de prueba" })
    .click();
  await expect(
    page.getByLabel("Versión para probar").locator("option"),
  ).toHaveCount(2);
  await request.post(
    "http://127.0.0.1:3132/__workspace-publication/legacy-recovery",
    {
      headers: {
        Authorization: `Bearer e30.${Buffer.from(JSON.stringify({ app_metadata: { platform_role: "platform_admin" } })).toString("base64url")}.test`,
      },
    },
  );
  await page.reload();
  await expect(
    page.getByLabel("Versión para probar").locator("option"),
  ).toHaveCount(1);
  await page
    .getByRole("combobox", { name: /^Número destino/ })
    .selectOption({ index: 1 });
  await page
    .getByText("Volver a una versión anterior", { exact: true })
    .click();
  await page
    .getByRole("combobox", { name: /^Versión anterior/ })
    .selectOption({ index: 1 });
  await expect(
    page.getByText("Conocimiento aprobado", { exact: true }).first(),
  ).toBeVisible();
  await expect(
    page
      .locator("pre")
      .filter({ hasText: "Conocimiento congelado para comparar" })
      .first(),
  ).toBeVisible();
  await page.getByLabel("Confirmo recuperar esta versión").check();
  await expect(
    page.getByRole("button", { name: "Recuperar versión" }),
  ).toBeEnabled();
});

test("an accepted preview with lost response is retried with the same identity", async ({
  page,
}) => {
  await page.goto(path);
  await page
    .getByRole("button", { name: "Preparar versión de prueba" })
    .click();
  await page.getByLabel("Versión para probar").selectOption({ index: 1 });
  await page.getByLabel("Mensaje de prueba").fill("respuesta-perdida");
  await page.getByRole("button", { name: "Enviar prueba aislada" }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "No se pudo confirmar" }),
  ).toBeVisible();
  await expect(page.getByLabel("Mensaje de prueba")).toHaveValue(
    "respuesta-perdida",
  );
  await page.getByRole("button", { name: "Enviar prueba aislada" }).click();
  await expect(page.getByLabel("Mensajes de la prueba")).toContainText(
    "Respuesta simulada de Zuvel",
  );
  await expect(
    page.getByLabel("Conversaciones de prueba guardadas").locator("option"),
  ).toHaveCount(2);
});

test("a selected scenario remains inspectable and approvable outside the first runs page", async ({
  page,
  request,
}) => {
  await page.goto(path);
  await page
    .getByRole("button", { name: "Preparar versión de prueba" })
    .click();
  await page.getByLabel("Versión para probar").selectOption({ index: 1 });
  await page.getByRole("button", { name: "Ejecutar escenarios" }).click();
  await expect(
    page.getByLabel("He revisado las respuestas exactas"),
  ).toBeVisible();
  await request.post(
    "http://127.0.0.1:3132/__workspace-publication/hide-suites",
    {
      headers: {
        Authorization: `Bearer e30.${Buffer.from(JSON.stringify({ app_metadata: { platform_role: "platform_admin" } })).toString("base64url")}.test`,
      },
    },
  );
  await page.getByRole("button", { name: "Consultar estado" }).click();
  await page.getByLabel("He revisado las respuestas exactas").check();
  await page.getByRole("button", { name: "Aprobar escenarios" }).click();
  await expect(
    page.getByText("Decisión: Aprobada.", { exact: false }),
  ).toBeVisible();
});

test("refresh keeps a later candidate page and its unsent preview", async ({
  page,
  request,
}) => {
  await page.goto(path);
  await page
    .getByRole("button", { name: "Preparar versión de prueba" })
    .click();
  await expect(
    page.getByLabel("Versión para probar").locator("option"),
  ).toHaveCount(2);
  await request.post(
    "http://127.0.0.1:3132/__workspace-publication/page-two-only",
    {
      headers: {
        Authorization: `Bearer e30.${Buffer.from(JSON.stringify({ app_metadata: { platform_role: "platform_admin" } })).toString("base64url")}.test`,
      },
    },
  );
  await page.goto(path + "?section=candidates&cursor=page-two");
  await page.getByLabel("Versión para probar").selectOption({ index: 1 });
  await page
    .getByLabel("Mensaje de prueba")
    .fill("Sin enviar en segunda página");
  await page.getByRole("button", { name: "Consultar estado" }).click();
  await expect(page.getByLabel("Mensaje de prueba")).toHaveValue(
    "Sin enviar en segunda página",
  );
  await expect(
    page.getByLabel("Versión para probar").locator("option"),
  ).toHaveCount(2);
});
