import { expect, test } from "@playwright/test";

test("tenant wizard resumes Agent Drafts and rejects stale edits", async ({
  page,
  context,
}) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("admin@example.test");
  await page.getByLabel("Password").fill("valid-admin");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(
    page.getByRole("heading", { name: "Operational dashboard" }),
  ).toBeVisible();

  await page.goto("/tenants/new");
  await page.getByLabel("Display name").fill("Café Aurora");
  await page.getByLabel("Legal name").fill("Café Aurora SAS");
  await page.getByLabel("Tenant slug").fill("cafe-aurora");
  await page.getByLabel("Industry").fill("Hospitality");
  await page.getByRole("button", { name: "Create and continue" }).click();
  await expect(
    page.getByRole("heading", { name: "Café Aurora" }),
  ).toBeVisible();
  await expect(page.getByText("Business profile")).toBeVisible();

  await page.getByRole("link", { name: "Agent", exact: true }).click();
  await page.getByRole("button", { name: "Create Agent Draft" }).click();
  await expect(page.getByText("Version 1", { exact: true })).toBeVisible();
  await expect(page.getByText("Not published yet")).toBeVisible();

  await page.getByLabel("Agent name").fill("Aurora");
  await page.getByLabel("Tone").selectOption({ label: "Cálido y empático" });
  await page.getByLabel("Formality").selectOption({ label: "Usted" });
  await page
    .getByLabel("Brand vocabulary")
    .fill("con mucho gusto, café de origen");
  await page
    .getByLabel("Initial greeting")
    .fill("¡Hola! Soy Aurora. ¿Qué te gustaría disfrutar hoy?");
  await page
    .locator("form", { has: page.getByLabel("Agent name") })
    .getByRole("button", { name: "Save as new Draft" })
    .click();
  await expect(page.getByText("Version 2", { exact: true })).toBeVisible();

  await page.getByLabel("Primary language").selectOption("en-US");
  await page
    .locator("form", { has: page.getByLabel("Primary language") })
    .getByRole("button", { name: "Save as new Draft" })
    .click();
  await expect(page.getByText("Version 3", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Agent name")).toHaveValue("Aurora");
  await expect(page.getByLabel("Primary language")).toHaveValue("en-US");
  await expect(page.locator("textarea")).toHaveCount(2);
  await expect(page.getByText("YAML", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel(/model/i)).toHaveCount(0);
  await expect(page.getByRole("option")).toHaveCount(8);

  const stalePage = await context.newPage();
  await stalePage.goto(page.url());
  await expect(stalePage.getByText("Version 3", { exact: true })).toBeVisible();

  await page
    .getByLabel("Initial greeting")
    .fill("¡Hola! Bienvenido a Café Aurora.");
  await page
    .locator("form", { has: page.getByLabel("Agent name") })
    .getByRole("button", { name: "Save as new Draft" })
    .click();
  await expect(page.getByText("Version 4", { exact: true })).toBeVisible();

  await stalePage
    .getByLabel("Tone")
    .selectOption({ label: "Profesional y directo" });
  await stalePage
    .locator("form", { has: stalePage.getByLabel("Agent name") })
    .getByRole("button", { name: "Save as new Draft" })
    .click();
  await expect(stalePage.locator(".form-notice-error")).toContainText(
    "Another administrator saved a newer Draft",
  );
  await expect(stalePage.getByText("Version 4", { exact: true })).toBeVisible();
});
