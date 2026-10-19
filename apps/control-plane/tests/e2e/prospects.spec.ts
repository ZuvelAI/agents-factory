import { expect, test } from "@playwright/test";
const tenant = "019c2000-0000-7000-8000-000000000102";
const first = "019c2000-0000-7000-8000-000000000901";
const later = "019c2000-0000-7000-8000-000000000903";
test.beforeEach(async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("admin@example.test");
  await page.getByLabel("Password").fill("valid-admin");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/$/);
});
test("prospect list and detail preserve context, filters and exact conversation links", async ({
  page,
}) => {
  await page.goto(`/prospects?tenant=${tenant}&prospect=${first}`);
  await expect(
    page.getByRole("heading", { name: "Prospectos", exact: true }),
  ).toBeVisible();
  const detail = page.getByRole("region", { name: "Detalle del prospecto" });
  await expect(
    detail.getByRole("heading", { name: "Valentina Rojas" }),
  ).toBeVisible();
  await expect(detail).toContainText("Nexo Estudio");
  await expect(detail).toContainText("Agente comercial");
  await expect(
    detail.getByRole("link", { name: "Ver conversación", exact: true }).first(),
  ).toHaveAttribute("href", /conversation-log\?tenant=.*conversation=/);
  await page.getByLabel("Buscar prospectos").fill("Andrés");
  await page.getByRole("button", { name: "Buscar", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "Lista de prospectos" }),
  ).toContainText("Andrés Molina");
});
test("detail outside the current list page and literal HTML stay safe", async ({
  page,
}) => {
  await page.goto(`/prospects?tenant=${tenant}&prospect=${later}`);
  await expect(
    page.getByRole("region", { name: "Detalle del prospecto" }),
  ).toContainText("Laura Torres");
  await page.goto(`/prospects?tenant=${tenant}&q=html`);
  await expect(
    page.getByRole("region", { name: "Lista de prospectos" }),
  ).toContainText("<script>ejemplo</script>");
  expect(
    await page.locator("script").filter({ hasText: "ejemplo" }).count(),
  ).toBe(0);
});
test("errors never masquerade as no prospects and mobile stays usable", async ({
  page,
}) => {
  await page.goto(`/prospects?tenant=${tenant}&q=trigger-error`);
  await expect(page.locator(".workspace [role=alert]")).toContainText(
    "No pudimos consultar",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/prospects?tenant=${tenant}&prospect=${first}`);
  await expect(
    page.getByRole("region", { name: "Detalle del prospecto" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "/private/tmp/prospectos-mobile.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 1050 });
  await page.screenshot({
    path: "/private/tmp/prospectos-desktop.png",
    fullPage: true,
  });
});
test("empty search is distinct, source links are keyboard reachable, privacy flags visible", async ({
  page,
}) => {
  await page.goto(`/prospects?tenant=${tenant}&q=no-match`);
  await expect(
    page.getByRole("region", { name: "Lista de prospectos" }),
  ).toContainText("No hay prospectos para estos filtros");
  await page.goto(
    `/prospects?tenant=${tenant}&prospect=019c2000-0000-7000-8000-000000000904`,
  );
  const detail = page.getByRole("region", { name: "Detalle del prospecto" });
  await expect(detail).toContainText("Identidad en conflicto");
  await expect(detail).toContainText("Captura detenida por solicitud");
  const link = detail.getByRole("link", {
    name: "Ver conversación",
    exact: true,
  });
  await link.focus();
  await expect(link).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/conversation-log\?tenant=.*conversation=/);
  await expect(
    page.getByRole("link", { name: "Ver prospecto", exact: true }),
  ).toBeVisible();
});
