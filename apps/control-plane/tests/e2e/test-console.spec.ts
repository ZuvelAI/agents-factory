import { expect, test } from "@playwright/test";

const tenantId = "019c2000-0000-7000-8000-000000000101";
const backendHeaders = { Authorization: "Bearer test-platform-admin" };

test("inspects a safe simulated run and blocks unconfigured real tests", async ({
  page,
  request,
}) => {
  await signIn(page);
  await page.goto("/test-console");
  await expect(
    page.getByRole("heading", { name: "Test Console" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Open safe console" }).click();

  await expect(page.getByLabel("Real test environment")).toBeDisabled();
  await expect(
    page.getByText(/dedicated test tenant and provider accounts/i),
  ).toBeVisible();
  await expect(
    page.getByText(/Production writes are impossible/i),
  ).toBeVisible();
  await page.getByLabel("Customer message").fill("Please cancel order 1042.");
  await page.getByRole("button", { name: "Run test conversation" }).click();

  await expect(
    page.getByRole("heading", { name: "Simulated result" }),
  ).toBeVisible();
  await expect(
    page.getByText("request_order_cancellation", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("orders", { exact: true })).toBeVisible();
  for (const section of [
    "AgentSpec",
    "Knowledge",
    "Identity",
    "Tools",
    "Sources",
    "Action",
    "Approval",
    "Usage & cost",
  ]) {
    await expect(page.getByRole("heading", { name: section })).toBeVisible();
  }
  await expect(
    page
      .getByRole("article")
      .filter({ has: page.getByRole("heading", { name: "Action" }) })
      .getByText('"external_effect": false'),
  ).toBeVisible();
  await expect(page.getByText('"external_requests": 0')).toBeVisible();

  const rejectedRealRun = await request.post(
    `http://127.0.0.1:8000/admin/tenants/${tenantId}/test-console/runs`,
    {
      headers: backendHeaders,
      data: { mode: "REAL_TEST_ENVIRONMENT", message: "Test a real order." },
    },
  );
  expect(rejectedRealRun.status()).toBe(409);
  await expect(rejectedRealRun.json()).resolves.toMatchObject({
    code: "real_test_environment_required",
  });
  const productionCalls = await (
    await request.get("http://127.0.0.1:8000/__test/production-call-count")
  ).json();
  expect(productionCalls.calls).toBe(0);
});

async function signIn(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill("admin@example.test");
  await page.getByLabel("Password").fill("valid-admin");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(
    page.getByRole("heading", { name: "Operational dashboard" }),
  ).toBeVisible();
}
