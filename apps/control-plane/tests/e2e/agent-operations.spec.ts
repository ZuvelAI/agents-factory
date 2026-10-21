import { expect, test } from "@playwright/test";
const tenant = "019c2000-0000-7000-8000-000000000102",
  agent = "019c2000-0000-7000-8000-000000000501";
const path = `/tenants/${tenant}/agents/${agent}`;
const headers = {
  Authorization: `Bearer e30.${Buffer.from(JSON.stringify({ app_metadata: { platform_role: "platform_admin" } })).toString("base64url")}.test`,
};
let browserErrors: string[] = [];
test.beforeEach(async ({ page, request }) => {
  browserErrors = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));
  await request.post("http://127.0.0.1:3132/__agent-operation/reset", {
    headers,
  });
  await page.goto("/login");
  await page.getByLabel("Email").fill("admin@example.test");
  await page.getByLabel("Password").fill("valid-admin");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/$/);
  await page.goto(path);
});
test.afterEach(() => {
  expect(browserErrors).toEqual([]);
});
test("pause requires confirmation and resume only promises new messages", async ({
  page,
  request,
}) => {
  const control = page.getByRole("region", { name: "Operación del agente" });
  const summary = control.locator("summary");
  await summary.focus();
  await page.keyboard.press("Enter");
  await expect(
    control.getByText(/Un envío ya iniciado podría llegar/),
  ).toBeVisible();
  await control.getByRole("button", { name: "Cancelar", exact: true }).click();
  expect(
    (
      await (
        await request.get("http://127.0.0.1:3132/__agent-operation/stats", {
          headers,
        })
      ).json()
    ).attempts,
  ).toBe(0);
  await summary.click();
  await control
    .getByRole("button", { name: "Confirmar pausa", exact: true })
    .click();
  await expect(
    control.getByText("Respuestas automáticas pausadas", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Pausado", { exact: true })).toBeVisible();
  await control.locator("summary").click();
  await expect(
    control.getByText(/Solo responderá mensajes nuevos/),
  ).toBeVisible();
  await control
    .getByRole("button", { name: "Confirmar reactivación", exact: true })
    .click();
  await expect(
    control.getByText("Respuestas automáticas habilitadas", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Archivar", exact: true }),
  ).toHaveCount(0);
});
test("conflict requires refresh and never pretends mutation succeeded", async ({
  page,
  request,
}) => {
  await request.post("http://127.0.0.1:3132/__agent-operation/mode", {
    headers,
    data: { mode: "conflict" },
  });
  const control = page.getByRole("region", { name: "Operación del agente" });
  await control.locator("summary").click();
  await control
    .getByRole("button", { name: "Confirmar pausa", exact: true })
    .click();
  await expect(control.getByRole("alert")).toContainText("El estado cambió");
  await control.getByRole("button", { name: "Recargar estado" }).click();
  await expect(
    control.getByText("Respuestas automáticas pausadas", { exact: true }),
  ).toBeVisible();
});
test("pending disables duplicate submission and errors keep last confirmed state", async ({
  page,
  request,
}) => {
  await request.post("http://127.0.0.1:3132/__agent-operation/mode", {
    headers,
    data: { mode: "slow" },
  });
  const control = page.getByRole("region", { name: "Operación del agente" });
  await control.locator("summary").click();
  await control
    .getByRole("button", { name: "Confirmar pausa", exact: true })
    .click();
  await expect(
    control.getByRole("button", { name: "Guardando estado…" }),
  ).toBeDisabled();
  await expect(
    control.getByRole("button", { name: "Recargar estado" }),
  ).toBeDisabled();
  await expect(
    control.getByText("Respuestas automáticas pausadas", { exact: true }),
  ).toBeVisible();
  expect(
    (
      await (
        await request.get("http://127.0.0.1:3132/__agent-operation/stats", {
          headers,
        })
      ).json()
    ).attempts,
  ).toBe(1);
  await request.post("http://127.0.0.1:3132/__agent-operation/mode", {
    headers,
    data: { mode: "error" },
  });
  await control.locator("summary").click();
  await control
    .getByRole("button", { name: "Confirmar reactivación", exact: true })
    .click();
  await expect(control.getByRole("alert")).toContainText(
    "No pudimos confirmar",
  );
  await expect(
    control.getByText("Respuestas automáticas pausadas", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("SYNTHETIC_PRIVATE_DIAGNOSTIC")).toHaveCount(0);
});
test("disabled installation offers no state mutation and fits mobile", async ({
  page,
  request,
}) => {
  await request.post("http://127.0.0.1:3132/__agent-operation/mode", {
    headers,
    data: { mode: "disabled" },
  });
  await page.setViewportSize({ width: 390, height: 900 });
  await page.reload();
  const control = page.getByRole("region", { name: "Operación del agente" });
  await expect(control.getByText(/Control no disponible/)).toBeVisible();
  await expect(control.locator("summary")).toHaveCount(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
