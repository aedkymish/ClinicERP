import { expect, test, type Page } from "@playwright/test";

const USER = process.env.E2E_USER ?? "admin";
const PASSWORD = process.env.E2E_PASSWORD ?? "";
const BASE = process.env.E2E_BASE_URL ?? "http://localhost:3000";
const stamp = Date.now().toString().slice(-6);

async function signIn(page: Page) {
  await page.goto("/login");
  await page.getByLabel(/username|اسم المستخدم/i).fill(USER);
  await page.getByLabel(/^password|كلمة المرور/i).fill(PASSWORD);
  await page.getByRole("button", { name: /sign in|دخول/i }).click();
  await expect(page.getByRole("heading", { name: /dashboard|لوحة التحكم/i })).toBeVisible();
}

test.beforeEach(async ({ page }) => {
  test.skip(!PASSWORD, "set E2E_PASSWORD to run the UI tests");
  await page.context().clearCookies();
  await page.context().addCookies([{ name: "lang", value: "en", url: BASE }]);
});

test("unauthenticated pages redirect to sign-in", async ({ page }) => {
  await page.goto("/billing");
  await expect(page).toHaveURL(/\/login/);
});

test("wrong password shows an in-page error, never a browser dialog", async ({ page }) => {
  page.on("dialog", () => { throw new Error("browser dialog used (UI-06)"); });
  await page.goto("/login");
  await page.getByLabel(/username/i).fill(`nobody-${stamp}`); // never lock a real account
  await page.getByLabel(/^password/i).fill("definitely-wrong");
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.locator("form [role=alert]")).toContainText(/wrong username or password/i);
});

test("book → invoice → pay: the front-desk flow", async ({ page }) => {
  await signIn(page);
  // new patient
  await page.goto("/patients");
  await page.getByRole("button", { name: /new patient/i }).click();
  const dlg = page.getByRole("dialog");
  await dlg.getByLabel(/^name/i).fill(`E2E Patient ${stamp}`);
  await dlg.getByLabel(/^phone/i).fill(`07${stamp}99`);
  await dlg.getByRole("button", { name: /^save$/i }).click();
  const dup = dlg.getByRole("button", { name: /create anyway/i });
  if (await dup.isVisible().catch(() => false)) await dup.click();
  await expect(page.getByRole("heading", { name: `E2E Patient ${stamp}` })).toBeVisible();

  // draft invoice from the patient file
  await page.getByRole("tab", { name: /billing/i }).click();
  await page.getByRole("button", { name: /new invoice/i }).click();
  await page.getByRole("button", { name: /add line/i }).click();
  await page.getByRole("button", { name: /save draft/i }).click();
  await expect(page).toHaveURL(/\/billing\/\d+$/);
  await expect(page.getByText(/^Draft$/).first()).toBeVisible();

  // take full payment → invoice is posted and paid
  await page.getByRole("button", { name: /take payment/i }).click();
  await page.getByRole("dialog").getByRole("button", { name: /^save$/i }).click();
  await expect(page.getByText(/^Posted$/).first()).toBeVisible();
  await expect(page.getByText(/^Paid$/).first()).toBeVisible();
});

test("Arabic switches the layout to right-to-left", async ({ page }) => {
  await signIn(page);
  await page.getByRole("button", { name: "العربية" }).click();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.getByRole("heading", { name: "لوحة التحكم" })).toBeVisible();
  await page.getByRole("button", { name: "English" }).click();
  await expect(page.locator("html")).toHaveAttribute("dir", "ltr");
});

test("no horizontal page scroll on any main screen", async ({ page }) => {
  await signIn(page);
  for (const path of ["/", "/patients", "/appointments", "/billing", "/inventory", "/reports", "/settings"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, `${path} overflows by ${overflow}px`).toBeLessThanOrEqual(1);
  }
});
