import { expect, test } from "@playwright/test";

const tenantId = "019c2000-0000-7000-8000-000000000101";
const backendHeaders = { Authorization: "Bearer test-platform-admin" };

test("configures safe capabilities, connectors and approval routes", async ({
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

  await page.goto("/capabilities");
  await expect(
    page.getByRole("heading", { name: "Capability Packs" }),
  ).toBeVisible();
  await expect(page.locator(".capability-card")).toHaveCount(3);

  await page.goto(`/tenants/${tenantId}/capabilities`);
  await expect(page.getByText("Version 1", { exact: true })).toBeVisible();
  await expect(
    page.getByLabel("appointments.request_cancellation approval required"),
  ).toBeDisabled();
  const identity = page.getByLabel(
    "appointments.request_cancellation identity level",
  );
  await expect(identity.locator('option[value="1"]')).toBeDisabled();
  await expect(
    page
      .locator(".approval-route-card", {
        has: page.getByRole("heading", {
          name: "appointments.request_cancellation",
        }),
      })
      .getByText("Missing route"),
  ).toBeVisible();

  await page
    .locator(".capability-card", {
      has: page.getByRole("heading", { name: "Returns Claims" }),
    })
    .getByRole("checkbox")
    .check();
  await page
    .getByRole("button", { name: "Save capabilities as Draft" })
    .click();
  await expect(page.getByText("Version 2", { exact: true })).toBeVisible();

  await page.getByLabel("orders.get_status identity level").selectOption("2");
  await page
    .getByRole("button", { name: "Save stricter policy as Draft" })
    .click();
  await expect(page.getByText("Version 3", { exact: true })).toBeVisible();

  const approvalCard = page.locator(".approval-route-card", {
    has: page.getByRole("heading", {
      name: "appointments.request_cancellation",
    }),
  });
  await approvalCard
    .getByLabel("Authorized approver emails")
    .fill("owner@example.test");
  await approvalCard
    .getByRole("button", { name: "Save approval route" })
    .click();
  await expect(page.getByText("Version 4", { exact: true })).toBeVisible();
  await expect(
    page
      .locator(".approval-route-card", {
        has: page.getByRole("heading", {
          name: "appointments.request_cancellation",
        }),
      })
      .getByText("Route complete"),
  ).toBeVisible();

  await page.goto(`/tenants/${tenantId}/integrations`);
  const restCard = page.locator(".connector-card", {
    has: page.getByRole("heading", { name: "Generic REST API" }),
  });
  await expect(restCard.getByText("Coming later")).toBeVisible();
  await expect(restCard.getByRole("button")).toHaveCount(0);
  await expect(page.getByLabel("Enable Live Human Handoff")).toBeDisabled();

  let calendarCard = page.locator(".connector-card", {
    has: page.getByRole("heading", { name: "Google Calendar" }),
  });
  await expect(calendarCard.locator(".connection-heading strong")).toHaveText(
    "REAUTH REQUIRED",
  );
  await expect(calendarCard.locator(".health")).toBeVisible();
  await calendarCard.getByRole("button", { name: "Reconnect" }).click();
  calendarCard = page.locator(".connector-card", {
    has: page.getByRole("heading", { name: "Google Calendar" }),
  });
  await expect(calendarCard.locator(".connection-heading strong")).toHaveText(
    "CONNECTED",
  );

  await calendarCard.getByRole("button", { name: "Test health" }).click();
  calendarCard = page.locator(".connector-card", {
    has: page.getByRole("heading", { name: "Google Calendar" }),
  });
  await expect(calendarCard.locator(".health")).toHaveText("ERROR");
  const sheetsCard = page.locator(".connector-card", {
    has: page.getByRole("heading", { name: "Google Sheets" }),
  });
  await expect(sheetsCard.locator(".health")).toHaveText("HEALTHY");

  await calendarCard.getByRole("button", { name: "Test health" }).click();
  calendarCard = page.locator(".connector-card", {
    has: page.getByRole("heading", { name: "Google Calendar" }),
  });
  await expect(calendarCard.locator(".health")).toHaveText("HEALTHY");
  await calendarCard.getByLabel("calendar.get_event").check();
  await calendarCard
    .getByRole("button", { name: "Save mapping as Draft" })
    .click();
  await expect(
    page.getByText("Integration configuration saved."),
  ).toBeVisible();

  let rejectedMappingStatus = 0;
  let rejectedMappingBody: { code?: string } = {};
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const editor = await (
      await request.get(
        `http://127.0.0.1:8000/admin/tenants/${tenantId}/agent-instances/current`,
        { headers: backendHeaders },
      )
    ).json();
    const rejectedMapping = await request.post(
      `http://127.0.0.1:8000/admin/tenants/${tenantId}/agent-instances/${editor.instance.id}/connector-binding-drafts`,
      {
        headers: backendHeaders,
        data: {
          expected_version_id: editor.editable_version.id,
          connection_id: "42000000-0000-4000-8000-000000000040",
          connector_name: "google_sheets",
          operations: ["orders.delete_order"],
        },
      },
    );
    rejectedMappingStatus = rejectedMapping.status();
    rejectedMappingBody = await rejectedMapping.json();
    if (rejectedMappingBody.code !== "agent_spec_stale_write") break;
  }
  expect(rejectedMappingStatus).toBe(409);
  expect(rejectedMappingBody).toMatchObject({
    code: "connector_operation_unsupported",
  });
  const currentEditor = await (
    await request.get(
      `http://127.0.0.1:8000/admin/tenants/${tenantId}/agent-instances/current`,
      { headers: backendHeaders },
    )
  ).json();
  const rejectedHandoff = await request.post(
    `http://127.0.0.1:8000/admin/tenants/${tenantId}/agent-instances/${currentEditor.instance.id}/human-operations-drafts`,
    {
      headers: backendHeaders,
      data: {
        expected_version_id: currentEditor.editable_version.id,
        handoff_enabled: true,
      },
    },
  );
  expect(rejectedHandoff.status()).toBe(409);
  await expect(rejectedHandoff.json()).resolves.toMatchObject({
    code: "human_surface_required",
  });

  await page.reload();
  calendarCard = page.locator(".connector-card", {
    has: page.getByRole("heading", { name: "Google Calendar" }),
  });
  await calendarCard.getByRole("button", { name: "Revoke" }).click();
  await expect(
    page
      .locator(".connector-card", {
        has: page.getByRole("heading", { name: "Google Calendar" }),
      })
      .locator(".connection-heading strong"),
  ).toHaveText("REVOKED");
  await expect(
    page
      .locator(".connector-card", {
        has: page.getByRole("heading", { name: "Google Sheets" }),
      })
      .locator(".health"),
  ).toHaveText("HEALTHY");
});
