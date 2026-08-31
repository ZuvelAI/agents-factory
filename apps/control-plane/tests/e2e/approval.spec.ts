import { expect, test, type Page } from "@playwright/test";

const link = (character: string) =>
  `a1.${"1".repeat(32)}.${"2".repeat(32)}.${character.repeat(32)}.1999999999.${"a".repeat(64)}`;

async function verify(page: Page) {
  await page.getByLabel("Correo autorizado").fill("reviewer@example.test");
  await page
    .getByRole("button", { name: "Enviar código", exact: true })
    .click();
  await page.getByLabel("Código de verificación").fill("123456");
  await page.getByRole("button", { name: "Verificar y revisar" }).click();
  await expect(
    page.getByRole("heading", { name: "3. Revisa y decide" }),
  ).toBeVisible();
}

test("approval page: production CSP, OTP, safe result, replay and history", async ({
  page,
  request,
}, testInfo) => {
  const errors: string[] = [];
  const urls: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("request", (req) =>
    urls.push(req.url(), req.headers().referer ?? ""),
  );
  const response = await page.goto(`/approval/review#token=${link("3")}`);
  await expect(page.getByLabel("Correo autorizado")).toBeVisible();
  expect(page.url()).toBe("http://127.0.0.1:3132/approval/review");
  expect(response?.headers()["cache-control"]).toContain("no-store");
  expect(response?.headers()["referrer-policy"]).toBe("no-referrer");
  const csp = response?.headers()["content-security-policy"] ?? "";
  expect(csp).toContain("'nonce-");
  expect(csp).toContain("frame-ancestors 'none'");
  expect(csp).not.toContain("unsafe-inline");
  expect(csp).not.toContain("unsafe-eval");
  await expect(page.getByRole("navigation")).toHaveCount(0);
  await verify(page);
  await expect(page.getByText("42", { exact: true })).toBeVisible();
  await expect(page.getByText("hidden@example.test")).toHaveCount(0);
  await page.getByLabel("Aprobar solicitud", { exact: true }).check();
  await page
    .getByLabel("Motivo", { exact: true })
    .selectOption("customer_request");
  await page
    .getByLabel("Explicación para el registro interno")
    .fill("Revisión completada.");
  await page.getByLabel("Confirmo que revisé", { exact: false }).check();
  await page.screenshot({
    path: testInfo.outputPath("review-desktop.png"),
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Confirmar decisión", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Decisión registrada" }),
  ).toBeVisible();
  await expect(
    page.getByText(/pendiente de validación y ejecución/),
  ).toBeVisible();
  expect(await page.content()).not.toContain("refund_money");
  expect(await page.content()).not.toContain("untrusted raw connector output");
  for (const sensitive of [link("3"), "123456"]) {
    expect(
      urls.join("\n") + errors.join("\n") + (await page.content()),
    ).not.toContain(sensitive);
  }
  expect(
    await page.evaluate(() => [localStorage.length, sessionStorage.length]),
  ).toEqual([0, 0]);
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Enlace no disponible" }),
  ).toBeVisible();
  await page.goto(`/approval/review#token=${link("3")}`);
  await expect(
    page.getByRole("heading", { name: "Enlace no disponible" }),
  ).toBeVisible();
  await page.goto("/health/ready");
  await page.goBack();
  await expect(
    page.getByRole("heading", { name: "Enlace no disponible" }),
  ).toBeVisible();
  const forged = await request.post("/approval/review", {
    headers: { Origin: "https://untrusted.example", "Next-Action": "invalid" },
    data: {},
  });
  expect(forged.status()).toBe(403);
  expect((await request.get("/approval/not-a-link")).status()).toBe(404);
  const privatePage = await request.get("/", { maxRedirects: 0 });
  expect(privatePage.status()).toBe(307);
  expect(privatePage.headers().location).toContain("/login");
  expect(errors).toEqual([]);
});

test("mobile keyboard rejection, expired link and rate feedback", async ({
  page,
  request,
}, testInfo) => {
  const before = await (
    await request.get("http://127.0.0.1:8132/fixture/stats")
  ).json();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/approval/review#token=${link("4")}`);
  await verify(page);
  await page.getByLabel("Rechazar solicitud", { exact: true }).focus();
  await page.keyboard.press("Space");
  await page
    .getByLabel("Motivo", { exact: true })
    .selectOption("reviewer_rejected");
  await page
    .getByLabel("Explicación para el registro interno")
    .fill("Necesita revisión del negocio.");
  await page.getByLabel("Confirmo que revisé", { exact: false }).focus();
  await page.keyboard.press("Space");
  await page.screenshot({
    path: testInfo.outputPath("review-mobile.png"),
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page
    .getByRole("button", { name: "Confirmar decisión", exact: true })
    .focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByText("La solicitud no fue aprobada.", { exact: true }),
  ).toBeVisible();
  await page.goto(`/approval/review#token=${link("e")}`);
  await expect(
    page.getByRole("heading", { name: "Enlace no disponible" }),
  ).toBeVisible();
  await page.goto(`/approval/review#token=${link("f")}`);
  await expect(
    page.getByRole("alert").filter({ hasText: "Demasiados intentos" }),
  ).toBeVisible();
  expect(
    await (await request.get("http://127.0.0.1:8132/fixture/stats")).json(),
  ).toEqual({ decisions: before.decisions + 1 });
});
