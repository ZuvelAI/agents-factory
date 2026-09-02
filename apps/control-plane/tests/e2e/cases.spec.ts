import { expect, test, type Page } from "@playwright/test";

const tenantId = "019c2000-0000-7000-8000-000000000101";
const caseId = "70000000-0000-4000-8000-000000000043";
const backendHeaders = { Authorization: "Bearer test-platform-admin" };

test("filters and resolves an overdue case then traces recorded costs", async ({
  page,
  request,
}) => {
  await signIn(page);
  await page.goto("/cases");
  await expect(page.getByRole("heading", { name: "Cases" })).toBeVisible();

  await page.getByLabel("Priority").selectOption("CRITICAL");
  await page.getByLabel("Overdue only").check();
  await page.getByRole("button", { name: "Apply case filters" }).click();
  const caseCard = page.locator(".case-card").filter({
    has: page.getByRole("heading", { name: "Damaged product" }),
  });
  await expect(caseCard.getByText("CRITICAL", { exact: true })).toBeVisible();
  await expect(caseCard.getByText("Overdue", { exact: true })).toBeVisible();
  await expect(caseCard.getByText("Approved", { exact: true })).toBeVisible();
  await expect(caseCard.getByText("Platform admin ••••0043")).toBeVisible();

  await caseCard.getByText("Resolve this case").click();
  await page
    .getByLabel("Internal resolution reason")
    .fill("Backoffice confirmed the reviewed replacement.");
  await page
    .getByLabel("Customer-visible result")
    .fill("Your replacement was approved and is being prepared.");
  await page.getByRole("button", { name: "Resolve case" }).click();
  await expect(
    page.getByText("Case resolved with a recorded event"),
  ).toBeVisible();
  await expect(caseCard.getByText("Resolved", { exact: true })).toBeVisible();

  const resolvedWorkspace = await (
    await request.get(
      `http://127.0.0.1:8000/admin/tenants/${tenantId}/case-workspace`,
      { headers: backendHeaders },
    )
  ).json();
  expect(resolvedWorkspace.cases[0]).toMatchObject({
    id: caseId,
    status: "RESOLVED",
    latest_event: "STATE_CHANGED",
    latest_reason: "Backoffice confirmed the reviewed replacement.",
  });

  await page.goto(`/usage?tenant=${tenantId}`);
  await expect(
    page.getByRole("heading", { name: "Usage & Costs" }),
  ).toBeVisible();
  await expect(
    page.getByText("recorded data only", { exact: false }),
  ).toBeVisible();
  await expect(page.getByText("$12.34", { exact: false })).toBeVisible();

  for (const dimension of ["Conversation", "Case", "Action", "Tenant"]) {
    await page.getByRole("link", { name: dimension, exact: true }).click();
    await expect(page.getByText("$12.34", { exact: false })).toBeVisible();
  }
  await page.getByLabel("Revenue").fill("1000");
  await page.getByRole("button", { name: "Estimate margin" }).click();
  await expect(page.getByText("$1,000.00", { exact: false })).toBeVisible();
  await expect(page.getByText("98.77%", { exact: false })).toBeVisible();
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
