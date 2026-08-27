import { expect, test } from "@playwright/test";

test("a direct private-route request redirects to login", async ({ page }) => {
  await page.goto("/");

  await expect(page).toHaveURL(/\/login$/);
  await expect(
    page.getByRole("heading", { name: "Agents Factory" }),
  ).toBeVisible();
});

test("public-route descendants still require authentication", async ({
  page,
}) => {
  const finalPaths: string[] = [];
  for (const path of ["/login/child", "/health/ready/child"]) {
    await page.goto(path);
    finalPaths.push(new URL(page.url()).pathname);
  }

  expect(finalPaths).toEqual(["/login", "/login"]);
});

test("invalid credentials show a generic login failure", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("unknown@example.test");
  await page.getByLabel("Password").fill("wrong");
  await page.getByRole("button", { name: "Sign in" }).click();

  const loginError = page.locator("p[role='alert']");
  await expect(loginError).toHaveText("Unable to sign in.");
  await expect(loginError).not.toContainText("invalid_grant");
});

test("a signed-in non-admin cannot reach the private shell", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("user@example.test");
  await page.getByLabel("Password").fill("valid-user");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page).toHaveURL(/\/login\?error=invalid$/);
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
});

test("a platform admin reaches the shell, then server logout clears access", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("admin@example.test");
  await page.getByLabel("Password").fill("valid-admin");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page).toHaveURL(/\/$/);
  await expect(
    page.getByRole("heading", { name: "Platform foundation" }),
  ).toBeVisible();
  const labels = [
    "Dashboard",
    "Tenants",
    "Agents",
    "Capabilities",
    "Integrations",
    "Knowledge",
    "Conversations",
    "Cases",
    "Evals",
    "Usage & Costs",
    "Operations",
    "Settings",
  ];
  const navigation = page.getByRole("navigation", { name: "Control Plane" });
  await expect(navigation.getByRole("listitem")).toHaveText(labels);

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
});
