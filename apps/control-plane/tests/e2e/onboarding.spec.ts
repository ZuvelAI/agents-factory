import { expect, test } from "@playwright/test";

const tenantId = "019c2000-0000-7000-8000-000000000101";
const steps = [
  ["company", "Company"],
  ["agent", "Agent"],
  ["capabilities", "Capabilities"],
  ["integrations", "Integrations"],
  ["knowledge-conflict-review", "Knowledge & Conflict Review"],
  ["policies-identity", "Policies & Identity"],
  ["human-operations", "Human Operations"],
  ["approval-routes", "Approval Routes"],
  ["whatsapp", "WhatsApp"],
  ["test", "Test"],
  ["quality-gate", "Quality Gate"],
  ["production", "Production"],
] as const;

test("canonical onboarding resumes and invalidates downstream steps", async ({
  page,
  request,
}) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("admin@example.test");
  await page.getByLabel("Password").fill("valid-admin");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(
    page.getByRole("heading", { name: "Operational dashboard" }),
  ).toBeVisible();

  await page.goto(`/tenants/${tenantId}/onboarding/company`);
  await expect(page.getByText("10 of 12 complete")).toBeVisible();
  for (const [slug, name] of steps) {
    await expect(
      page.getByRole("link", { name: new RegExp(`^\\d+\\. ${name}`) }),
    ).toHaveAttribute("href", `/tenants/${tenantId}/onboarding/${slug}`);
  }
  await expect(page.getByRole("heading", { name: "Company" })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Required fields" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Validation", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Internal documentation" }),
  ).toBeVisible();

  await page.getByRole("link", { name: /^3\. Capabilities/ }).click();
  await expect(
    page.getByText("CUSTOM CONNECTOR", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("CUSTOM WORKFLOW", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("NEW CAPABILITY", { exact: true })).toBeVisible();

  await page.goto(`/tenants/${tenantId}`);
  await expect(
    page.getByRole("link", { name: "Continue onboarding" }),
  ).toHaveAttribute("href", `/tenants/${tenantId}/onboarding/quality-gate`);
  await page.getByRole("link", { name: "Continue onboarding" }).click();
  await expect(
    page.getByRole("heading", { name: "Quality Gate" }),
  ).toBeVisible();
  await expect(
    page.getByText("Unavailable", { exact: true }).first(),
  ).toBeVisible();
  await expect(page.getByText(/Task 45 must persist/)).toBeVisible();

  await page.getByRole("link", { name: /^12\. Production/ }).click();
  await expect(
    page.getByText(/Production requires the unavailable Task 45/),
  ).toBeVisible();

  const changed = await request.post(
    "http://127.0.0.1:8000/__test/onboarding/upstream-change",
  );
  expect(changed.ok()).toBeTruthy();
  await page.goto(`/tenants/${tenantId}/onboarding/test`);
  await expect(page.getByText("Stale", { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/newer Agent Draft exists/)).toBeVisible();
  await page.getByRole("link", { name: /^11\. Quality Gate/ }).click();
  await expect(
    page.getByText(/Complete the current Test candidate first/),
  ).toBeVisible();
});
