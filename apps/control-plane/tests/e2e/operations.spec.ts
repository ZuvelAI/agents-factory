import { expect, test, type Page } from "@playwright/test";

const tenantId = "019c2000-0000-7000-8000-000000000101";
const backendHeaders = { Authorization: "Bearer test-platform-admin" };

test("operates degraded work without SSH and keeps later controls unavailable", async ({
  page,
  request,
}) => {
  await signIn(page);
  await page.goto("/operations");
  await expect(page.getByRole("heading", { name: "Operations" })).toBeVisible();
  await expect(
    page.getByText("DEGRADED", { exact: true }).first(),
  ).toBeVisible();
  await expect(page.getByText("Orders worker")).toBeVisible();

  let calendar = page
    .locator(".operational-card")
    .filter({ has: page.getByRole("heading", { name: "Google calendar" }) });
  await expect(
    calendar.locator(".review-state", { hasText: "Reauth required" }),
  ).toBeVisible();
  await calendar.getByRole("button", { name: "Reconnect" }).click();
  calendar = page
    .locator(".operational-card")
    .filter({ has: page.getByRole("heading", { name: "Google calendar" }) });
  await calendar.getByRole("button", { name: "Check health" }).click();
  calendar = page
    .locator(".operational-card")
    .filter({ has: page.getByRole("heading", { name: "Google calendar" }) });
  await expect(
    calendar.locator(".review-state", { hasText: "Error" }),
  ).toBeVisible();
  await calendar.getByRole("button", { name: "Check health" }).click();
  calendar = page
    .locator(".operational-card")
    .filter({ has: page.getByRole("heading", { name: "Google calendar" }) });
  await expect(
    calendar.locator(".review-state", { hasText: "Healthy" }),
  ).toBeVisible();

  for (const action of ["Retry", "Discard", "Resolve"] as const) {
    const topic = `Orders ${action.toLowerCase()} fixture`;
    let card = page
      .locator(".dlq-card")
      .filter({ has: page.getByRole("heading", { name: topic }) });
    await card.getByText(action, { exact: true }).click();
    const actionForm = card.locator("details[open]");
    await actionForm
      .getByLabel("Operational reason")
      .fill(`${action} reviewed fixture safely.`);
    await actionForm
      .getByLabel(new RegExp(`confirm ${action.toLowerCase()}`, "i"))
      .check();
    await actionForm
      .getByRole("button", { name: `Confirm ${action.toLowerCase()}` })
      .click();
    card = page
      .locator(".dlq-card")
      .filter({ has: page.getByRole("heading", { name: topic }) });
    await expect(
      card.getByText(action === "Discard" ? "discarded" : "resolved", {
        exact: true,
      }),
    ).toBeVisible();
  }
  await expect(page.getByText("Job dead letter retry")).toBeVisible();
  await expect(page.getByText("Job dead letter discard")).toBeVisible();
  await expect(page.getByText("Job dead letter resolve")).toBeVisible();

  for (const task of ["Task 44", "Task 45", "Task 47"]) {
    await expect(page.getByText(task, { exact: false }).first()).toBeVisible();
  }
  await expect(
    page.getByRole("button", { name: "Quality Gate action unavailable" }),
  ).toBeDisabled();

  const rejectedGate = await request.post(
    `http://127.0.0.1:8000/admin/tenants/${tenantId}/release-controls/quality-gate`,
    { headers: backendHeaders },
  );
  expect(rejectedGate.status()).toBe(409);
  await expect(rejectedGate.json()).resolves.toMatchObject({
    code: "quality_gate_task_45_required",
  });

  const draftResponse = await request.post(
    `http://127.0.0.1:8000/admin/tenants/${tenantId}/conversations/60000000-0000-4000-8000-000000000001/eval-drafts`,
    {
      headers: backendHeaders,
      data: { reason: "Operations workspace regression fixture" },
    },
  );
  expect(draftResponse.status()).toBe(201);
  await page.goto(`/evals?tenant=${tenantId}`);
  await expect(page.getByRole("heading", { name: "Evals" })).toBeVisible();
  await expect(page.getByText("schema v1", { exact: false })).toBeVisible();
  await expect(page.getByText("quality_gate_task_45_required")).toBeVisible();

  await page.goto("/settings");
  await expect(
    page.getByRole("heading", { name: "Settings", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("arbitrary shell access are not exposed", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Production settings unavailable" }),
  ).toBeDisabled();
});

async function signIn(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill("admin@example.test");
  await page.getByLabel("Password").fill("valid-admin");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(
    page.getByRole("heading", { name: "Operational dashboard" }),
  ).toBeVisible();
}
