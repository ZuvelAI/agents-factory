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
    page.getByRole("link", { name: "Nuevo agente" }),
  ).toHaveAttribute("href", `/tenants/${tenant}/agents/new`);
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

test("agent detail expands with keyboard without publishing or starting signup", async ({
  page,
}) => {
  await page.goto(
    `/tenants/${tenant}/agents/019c2000-0000-7000-8000-000000000501`,
  );
  await expect(
    page.getByRole("heading", { name: "Configuración publicada" }),
  ).toBeVisible();
  const knowledge = page
    .locator("summary")
    .filter({ hasText: "Conocimiento de la empresa" })
    .first();
  await knowledge.focus();
  await page.keyboard.press("Enter");
  await expect(knowledge).toBeFocused();
  await expect(
    page
      .getByText("Análisis de datos para toma de decisiones.", { exact: true })
      .first(),
  ).toBeVisible();
  await page
    .locator("summary")
    .filter({ hasText: "Borrador sin publicar" })
    .click();
  await expect(
    page.getByText("Cambio de instrucciones sin publicar", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Probar cambios" }),
  ).toBeDisabled();
  await page.goto(
    "/tenants/019c2000-0000-7000-8000-000000000103/agents/019c2000-0000-7000-8000-000000000501",
  );
  await expect(
    page.getByRole("heading", { name: "Agente no disponible" }),
  ).toBeVisible();
  await expect(
    page.getByText("Orienta sobre los servicios de Zuvel."),
  ).toHaveCount(0);
});

test("company to agent to conversations preserves attribution and filters", async ({
  page,
}) => {
  await page.goto(
    `/tenants/${tenant}/agents/019c2000-0000-7000-8000-000000000501`,
  );
  await page.getByRole("link", { name: "Ver conversaciones" }).click();
  await expect(page).toHaveURL(/agent=019c2000-0000-7000-8000-000000000501/);
  await page
    .getByRole("link")
    .filter({ hasText: "Contacto de prueba" })
    .click();
  await expect(
    page.getByText("En Zuvel te ayudamos a mejorar tus ventas."),
  ).toBeVisible();
  await expect(page.getByText("Entregado", { exact: true })).toBeVisible();
  await expect(page.getByText(/Versión registrada/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Enviar mensaje" }),
  ).toHaveCount(0);
  await page
    .getByLabel("Agente", { exact: true })
    .selectOption("019c2000-0000-7000-8000-000000000502");
  await page.getByRole("button", { name: "Aplicar filtros" }).click();
  await expect(
    page.getByText("No hay conversaciones para estos filtros."),
  ).toBeVisible();
  await expect(
    page.getByText("En Zuvel te ayudamos a mejorar tus ventas."),
  ).toHaveCount(0);
  await page
    .getByLabel("Empresa", { exact: true })
    .selectOption("019c2000-0000-7000-8000-000000000103");
  await page.getByRole("button", { name: "Aplicar filtros" }).click();
  await expect(page.getByLabel("Agente", { exact: true })).toHaveValue("");
  await expect(page.getByText("Contacto de prueba")).toHaveCount(0);
});

test("empty company and legacy routes remain explicit and recoverable", async ({
  page,
}, testInfo) => {
  await page.goto("/tenants");
  await expect(page.getByText("Sin agentes", { exact: true })).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("empresas.png"),
    fullPage: true,
  });
  await page.goto("/tenants/019c2000-0000-7000-8000-000000000104");
  await expect(
    page.getByText("Esta empresa todavía no tiene agentes"),
  ).toBeVisible();
  await page
    .locator("summary")
    .filter({ hasText: "Administración avanzada" })
    .click();
  await expect(
    page.getByRole("link", { name: "Configuración anterior" }),
  ).toHaveAttribute(
    "href",
    "/tenants/019c2000-0000-7000-8000-000000000104/onboarding/company",
  );
  await page.goto(`/tenants/${tenant}/onboarding/agent`);
  await expect(
    page.getByRole("button", { name: "Guardar este paso" }),
  ).toBeVisible();
  await page.goto(
    `/tenants/${tenant}/agents/019c2000-0000-7000-8000-000000000501`,
  );
  await expect(
    page.getByRole("heading", { name: "Configuración publicada" }),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("agente.png"),
    fullPage: true,
  });
});

test("bookmarked detail remains readable outside list page during refresh", async ({
  page,
}) => {
  await page.goto(
    `/conversation-log?tenant=${tenant}&agent=019c2000-0000-7000-8000-000000000501&conversation=019c2000-0000-7000-8000-000000000303&cursor=off-page`,
  );
  await expect(
    page.getByText("En Zuvel te ayudamos a mejorar tus ventas."),
  ).toBeVisible();
  await page.getByRole("link", { name: "Actualizar", exact: true }).click();
  await expect(
    page.getByText("En Zuvel te ayudamos a mejorar tus ventas."),
  ).toBeVisible();
  await expect(
    page.getByText("Selecciona una conversación", { exact: true }),
  ).toHaveCount(0);
});
