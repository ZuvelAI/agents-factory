import { expect, test, type Page } from "@playwright/test";

const tenantId = "019c2000-0000-7000-8000-000000000101";
const backendHeaders = { Authorization: "Bearer test-platform-admin" };

test("filters, labels and exports an anonymized conversation regression", async ({
  page,
  request,
}) => {
  await signIn(page);
  await page.goto("/conversations");
  await expect(
    page.getByRole("heading", { name: "Conversations" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Review conversations" }).click();
  await expect(page.getByText("Customer ••••4242")).toBeVisible();

  for (const category of [
    "AI resolved",
    "Human handoff",
    "Tool failure",
    "Policy violation",
    "Complaint",
    "High-cost conversation",
    "Flagged conversation",
  ]) {
    await page.getByRole("link", { name: category }).click();
    await expect(page.getByText("Customer ••••4242")).toBeVisible();
  }

  await expect(
    page.getByText("Cancel order 1042", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByText("Your cancellation request", { exact: false }),
  ).toBeVisible();
  await expect(page.locator(".trace-panel code")).toHaveText("9".repeat(64));

  for (const label of [
    "Correct",
    "Incorrect",
    "Unsafe",
    "Knowledge problem",
    "Integration problem",
    "Model reasoning problem",
  ]) {
    await page.getByLabel(label, { exact: true }).check();
  }
  await page
    .getByLabel("Reviewer note")
    .fill("Keep as a complete reviewed regression example.");
  await page.getByRole("button", { name: "Save human review" }).click();
  await expect(page.getByText("Human review saved.")).toBeVisible();

  await page
    .getByRole("button", { name: "Export anonymized Eval Runner v0 Draft" })
    .click();
  await expect(
    page.getByText("Anonymized Eval Runner v0 Draft created"),
  ).toBeVisible();
  await expect(page.getByText("schema v1", { exact: false })).toBeVisible();
  const exportedDrafts = page.locator(".eval-draft-list");
  await expect(exportedDrafts).toContainText("[email]");
  await expect(exportedDrafts).not.toContainText("customer@example.test");

  const workspace = await (
    await request.get(
      `http://127.0.0.1:8000/admin/tenants/${tenantId}/conversations/review-workspace`,
      { headers: backendHeaders },
    )
  ).json();
  expect(workspace.eval_drafts).toHaveLength(1);
  expect(workspace.eval_drafts[0].payload).toMatchObject({
    schema_version: 1,
    input_turn: { active_capabilities: ["orders"] },
    expected: { credentials_absent: true },
    graders: [
      "response_exists",
      "selected_tools",
      "persisted_result",
      "credentials_absent",
    ],
  });
  expect(JSON.stringify(workspace.eval_drafts[0].payload)).not.toContain(
    "customer@example.test",
  );
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
