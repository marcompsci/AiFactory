import { expect, test } from "@playwright/test";

test("send a mission, approve publishing, and see it survive a refresh", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("status")).toContainText("Live", { timeout: 30_000 });
  await page.getByRole("button", { name: "Send to the city" }).click();

  // agents work, then the commander asks before publishing
  await expect(page.getByRole("button", { name: /needs your approval/ })).toBeVisible({ timeout: 60_000 });
  await page.getByRole("tab", { name: /Approvals/ }).click();
  await page.getByRole("button", { name: "Approve and publish" }).click();

  await page.getByRole("tab", { name: /Missions/ }).click();
  await expect(page.getByText("Outcome: Published")).toBeVisible({ timeout: 60_000 });

  // inspect a real artifact
  await page.getByRole("button", { name: /Reviewable diff/ }).click();
  await expect(page.getByRole("dialog")).toContainText("ordered[mid - 1] + ordered[mid]");
  await page.getByRole("button", { name: "Close" }).click();

  // state comes back from the server after a reload (reconnection + snapshot hydration)
  await page.reload();
  await expect(page.getByRole("status")).toContainText("Live", { timeout: 30_000 });
  await expect(page.getByText(/Completed/).first()).toBeVisible();

  // activity feed shows stored events
  await page.getByRole("tab", { name: /Activity/ }).click();
  await expect(page.getByText("Approval granted")).toBeVisible();
});

test("agent inspector opens from the roster", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("tab", { name: /Agents/ }).click();
  await page.getByRole("button", { name: /Sentry QA Tester/ }).click();
  await expect(page.getByText("Permissions")).toBeVisible();
  await expect(page.getByText("run_tests", { exact: true }).first()).toBeVisible();
});

test("phone layout keeps the command panel usable", async ({ browser }) => {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
  await page.goto("http://localhost:3100/");
  await expect(page.getByRole("tab", { name: "Missions" })).toBeVisible();
  await page.getByRole("tab", { name: "System" }).click();
  await expect(page.getByText("Emergency stop")).toBeVisible();
});

test("with no server reachable, the app runs a clearly labeled demo", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => localStorage.setItem("aiciv.connection", JSON.stringify({ apiUrl: "http://localhost:9", token: "" })));
  await page.reload();
  await expect(page.getByRole("status")).toContainText("Demo, no server");
  await expect(page.getByText(/demo with no backend/)).toBeVisible();
  await expect(page.getByRole("button", { name: /needs your approval/ })).toBeVisible({ timeout: 60_000 });
  await page.getByRole("tab", { name: /Approvals/ }).click();
  await expect(page.getByText("Vega needs your approval (demo)")).toBeVisible();
  await page.getByRole("button", { name: "Approve and publish" }).click();
  await page.getByRole("tab", { name: /Activity/ }).click();
  await expect(page.getByText("Mission completed").first()).toBeVisible({ timeout: 20_000 });
  await page.evaluate(() => localStorage.removeItem("aiciv.connection"));
});
