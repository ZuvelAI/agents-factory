import { expect, test } from "@playwright/test";
const tenant = "019c2000-0000-7000-8000-000000000102";
const conversation = "019c2000-0000-7000-8000-000000000303";
test.beforeEach(async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("admin@example.test");
  await page.getByLabel("Password").fill("valid-admin");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/$/);
});
for (const view of ["conversation-log", "conversations"]) {
  test(`${view} labels and escapes audio on desktop and mobile`, async ({
    page,
  }) => {
    const extra =
      view === "conversation-log" ? "&messagesCursor=audio-ready" : "";
    await page.goto(
      `/${view}?tenant=${tenant}&conversation=${conversation}${extra}`,
    );
    const audio = page.getByRole("region", { name: "Nota de voz" });
    await expect(audio).toContainText("Transcripción automática");
    await expect(audio).toContainText("<script>audio-fixture</script>");
    expect(await page.locator("audio").count()).toBe(0);
    expect(
      await page.locator("script").filter({ hasText: "audio-fixture" }).count(),
    ).toBe(0);
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(audio).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    const navigation = page.locator("a[href]:visible").first();
    await expect(navigation).toBeVisible();
    await navigation.focus();
    await expect(navigation).toBeFocused();
  });
}
test("pending audio and failed message query remain distinguishable", async ({
  page,
}) => {
  await page.goto(
    `/conversations?tenant=${tenant}&conversation=${conversation}&messagesOffset=50`,
  );
  await expect(page.getByRole("region", { name: "Nota de voz" })).toContainText(
    "En espera",
  );
  await page.goto(
    `/conversations?tenant=${tenant}&conversation=${conversation}&messagesOffset=100`,
  );
  await expect(
    page.locator("[role=alert]").filter({ hasText: "mensajes" }),
  ).toBeVisible();
  expect(await page.getByRole("region", { name: "Nota de voz" }).count()).toBe(
    0,
  );
});
