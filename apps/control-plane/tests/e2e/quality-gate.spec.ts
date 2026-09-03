import { expect, test, type Page } from "@playwright/test";

const tenantId = "019c2000-0000-7000-8000-000000000101";

test("persists and displays exact-version Production Quality Gate evidence", async ({
  page,
  request,
}) => {
  const response = await request.post(
    `http://127.0.0.1:8000/admin/tenants/${tenantId}/evals/quality-gate/runs`,
    {
      headers: { Authorization: "Bearer test-platform-admin" },
      data: {
        agent_spec_digest: "a".repeat(64),
        knowledge_digest: "b".repeat(64),
        code_digest: "c".repeat(64),
      },
    },
  );
  expect(response.ok()).toBeTruthy();
  await expect(response.json()).resolves.toMatchObject({
    passed: true,
    failed_cases: 0,
    hard_blockers: [],
  });

  await signIn(page);
  await page.goto(`/evals?tenant=${tenantId}`);
  await expect(page.getByRole("heading", { name: "Evals" })).toBeVisible();
  await expect(page.getByText("Passed", { exact: true })).toBeVisible();
  await expect(page.getByText(/79 passed · 0 failed/)).toBeVisible();
  await expect(
    page.getByText("77000000-0000-4000-8000-000000000001"),
  ).toBeVisible();
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
