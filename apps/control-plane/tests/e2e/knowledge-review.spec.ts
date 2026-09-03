import { expect, test, type Page } from "@playwright/test";

const tenantId = "019c2000-0000-7000-8000-000000000101";
const backendHeaders = { Authorization: "Bearer test-platform-admin" };

test("reviews sources, conflicts, diffs and Knowledge versions", async ({
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

  await page.goto("/knowledge");
  await expect(
    page.getByRole("heading", { name: "Knowledge workspaces" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Review Knowledge" }).click();
  await expect(page.getByText("v1 · immutable")).toBeVisible();
  await expect(
    page.getByText("Draft v2 — review required", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Publish Production" }),
  ).toBeDisabled();
  await expect(
    page.getByText("production_quality_gate_required"),
  ).toBeVisible();

  await addSource(page, {
    name: "Public help website",
    type: "WEBSITE",
    authority: "AUTHORITATIVE",
    field: "HTTPS address",
    value: "https://example.test/help",
  });
  await addSource(page, {
    name: "Operations PDF",
    type: "PDF",
    authority: "SECONDARY",
    file: {
      name: "operations.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.concat([
        Buffer.from("%PDF-1.4 fixture"),
        Buffer.alloc(40 * 1024),
      ]),
    },
  });
  await addSource(page, {
    name: "Service handbook",
    type: "DOCX",
    authority: "SECONDARY",
    file: {
      name: "handbook.docx",
      mimeType:
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      buffer: Buffer.from("docx fixture"),
    },
  });
  await addSource(page, {
    name: "Drive policy",
    type: "GOOGLE_DRIVE",
    authority: "REFERENCE",
    field: "Google Drive file ID",
    value: "drive-file-123",
  });
  await addSource(page, {
    name: "Product catalog",
    type: "SPREADSHEET",
    authority: "AUTHORITATIVE",
    file: {
      name: "catalog.xlsx",
      mimeType:
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      buffer: Buffer.from("xlsx fixture"),
    },
  });
  await addSource(page, {
    name: "Owner guidance",
    type: "MANUAL",
    authority: "AUTHORITATIVE",
    field: "Approved business content",
    value: "Always verify the customer before sharing order details.",
  });
  await expect(page.locator(".source-card")).toHaveCount(7);

  const hoursProposal = page.locator(".proposal-card", {
    has: page.getByRole("heading", { name: "business.hours" }),
  });
  await hoursProposal
    .getByLabel(/Approved value/)
    .fill('{"open":"08:00","close":"18:00"}');
  await hoursProposal
    .getByRole("button", { name: "Save edited value" })
    .click();
  await expect(
    page.locator(".conflict-card", { hasText: "business.hours" }),
  ).toContainText("Resolved by human review: EDITED");

  await page
    .locator(".proposal-card", { hasText: "Outdated returns note" })
    .getByRole("button", { name: "Reject proposal" })
    .click();
  await page
    .locator(".proposal-card", { hasText: "Delivery coverage" })
    .getByRole("button", { name: "Approve proposal" })
    .click();
  await expect(page.locator(".proposal-card .review-proposed")).toHaveCount(0);
  await expect(page.locator(".diff-card")).toContainText(
    "Business hours and policy content changed",
  );

  let draft = page.locator(".knowledge-version", { hasText: "Version 2" });
  await draft.getByRole("button", { name: "Prepare semantic index" }).click();
  draft = page.locator(".knowledge-version", { hasText: "Version 2" });
  await draft
    .getByRole("button", { name: "Promote to Test with v0 evals" })
    .click();
  await expect(
    page.locator(".knowledge-version", { hasText: "Version 2" }),
  ).toContainText("v0 passed");

  const blockedProduction = await request.post(
    `http://127.0.0.1:8000/admin/tenants/${tenantId}/knowledge/versions/55000000-0000-4000-8000-000000000002/production`,
    { headers: backendHeaders },
  );
  expect(blockedProduction.status()).toBe(409);
  await expect(blockedProduction.json()).resolves.toMatchObject({
    code: "production_quality_gate_required",
  });

  await page
    .locator(".source-card", { hasText: "Published business profile" })
    .getByRole("button", { name: "Synchronize source" })
    .click();
  await expect(page.getByText("v1 · immutable")).toBeVisible();
  await expect(
    page.getByText("Draft v3 — review required", { exact: false }),
  ).toBeVisible();
  await expect(page.getByText("Connected source update")).toBeVisible();
  await expect(page.getByText("Production remains immutable")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Publish Production" }),
  ).toBeDisabled();
});

async function addSource(
  page: Page,
  source: {
    name: string;
    type: string;
    authority: string;
    field?: string;
    value?: string;
    file?: { name: string; mimeType: string; buffer: Buffer };
  },
) {
  const form = page.locator(".knowledge-source-form");
  await form.getByLabel("Source name").fill(source.name);
  await form.getByLabel("Source type").selectOption(source.type);
  await form.getByLabel("Authority").selectOption(source.authority);
  if (source.file) {
    await form.getByLabel("Private source file").setInputFiles(source.file);
  } else if (source.field && source.value) {
    await form.getByLabel(source.field).fill(source.value);
  }
  await form
    .getByRole("button", { name: "Add source and synchronize" })
    .click();
  await expect(
    page.locator(".source-card", {
      has: page.getByRole("heading", { name: source.name }),
    }),
  ).toBeVisible();
}
