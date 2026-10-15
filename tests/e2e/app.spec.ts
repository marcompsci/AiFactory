import { expect, test } from "@playwright/test";

test("send a mission, approve publishing, and see it survive a refresh", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("status")).toContainText("Live", { timeout: 30_000 });
  await page.getByRole("button", { name: "Send to the city" }).click();

  // agents work, then the commander asks before publishing
  await expect(page.getByRole("button", { name: /needs your approval/ })).toBeVisible({ timeout: 60_000 });
  await page.getByRole("tab", { name: /Owner/ }).click();
  await page.getByRole("button", { name: "Approve and publish" }).click();

  await page.getByRole("tab", { name: /Tasks/ }).click();
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
  await expect(page.getByRole("tab", { name: "Tasks" })).toBeVisible();
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
  await page.getByRole("tab", { name: /Owner/ }).click();
  await expect(page.getByText("Vega needs your approval (demo)")).toBeVisible();
  await page.getByRole("button", { name: "Approve and publish" }).click();
  await page.getByRole("tab", { name: /Activity/ }).click();
  await expect(page.getByText("Mission completed").first()).toBeVisible({ timeout: 20_000 });
  await page.evaluate(() => localStorage.removeItem("aiciv.connection"));
});

test("V4: research reaches the Owner's Tower and ships only after the owner approves", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("status")).toContainText("Live", { timeout: 30_000 });
  await page.getByRole("tab", { name: "Company" }).click();
  await page.getByRole("button", { name: "Start research" }).click();
  await expect(page.getByText(/fixture data/).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("button", { name: /waiting at your tower/ })).toBeVisible({ timeout: 90_000 });
  await page.getByRole("tab", { name: /Owner/ }).click();
  await expect(page.getByText("Atlas recommends you approve")).toBeVisible();
  await expect(page.getByText("Built on fixture research, not live market data")).toBeVisible();
  await expect(page.getByText(/\(the same bundle\)/)).toBeVisible();
  await expect(page.frameLocator('iframe[title="Prototype preview"]').getByRole("button", { name: "Log a focus session" })).toBeVisible();
  await page.getByRole("button", { name: "Approve this release" }).click();
  await page.getByRole("tab", { name: "Company" }).click();
  await expect(page.getByText("Release authorized").first()).toBeVisible({ timeout: 30_000 });
  await page.getByRole("tab", { name: "Activity" }).click();
  await expect(page.getByText(/Released to local release/).first()).toBeVisible({ timeout: 30_000 });
});

/** RFC 6238 TOTP, so the test can act as the owner's authenticator app. */
function totp(secret: string, at = Date.now()): string {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const crypto = require("node:crypto") as typeof import("node:crypto");
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const ch of secret.replace(/=+$/, "").toUpperCase()) bits += alphabet.indexOf(ch).toString(2).padStart(5, "0");
  const key = Buffer.from(bits.match(/.{8}/g)!.map((b) => parseInt(b, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(at / 1000 / 30)));
  const mac = crypto.createHmac("sha1", key).update(counter).digest();
  const off = mac[mac.length - 1] & 0x0f;
  return String((mac.readUInt32BE(off) & 0x7fffffff) % 1_000_000).padStart(6, "0");
}

test("V5: a paid-tool request travels through the AI Central Bank and is bought only after step-up approval", async ({ page }) => {
  test.setTimeout(300_000);
  await page.goto("/");
  await expect(page.getByRole("status")).toContainText("Live", { timeout: 30_000 });
  await page.getByRole("tab", { name: "Bank" }).click();
  await page.getByRole("button", { name: "Load simulated ledger" }).click();
  await expect(page.getByText(/SIMULATED DATA/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Available cash")).toBeVisible();
  await page.screenshot({ path: "test-results/v5-bank-dashboard.png" });

  await page.getByRole("button", { name: "Send to the bank" }).click();
  await page.getByRole("tab", { name: /Owner/ }).click();
  const decision = page.getByTestId("cost-decision").filter({ hasText: "Paid tool request" });
  await expect(decision).toBeVisible({ timeout: 200_000 });
  await expect(decision.getByText("Recommended option")).toBeVisible();
  await page.screenshot({ path: "test-results/v5-owner-decision.png" });

  await decision.getByRole("button", { name: "Approve exactly this" }).first().click();
  await page.getByRole("button", { name: "Set up an authenticator" }).click();
  const secret = (await page.getByTestId("totp-secret").textContent())!.trim();
  await page.getByLabel("6-digit code").fill(totp(secret));
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(decision).toHaveCount(0, { timeout: 30_000 });

  await page.getByRole("tab", { name: "Bank" }).click();
  await expect(page.getByRole("button", { name: /Figma: Professional/ }).getByText("Executed")).toBeVisible({ timeout: 60_000 });
  await page.getByRole("button", { name: /Figma: Professional/ }).click();
  await expect(page.getByText(/^Purchase .* to /).first()).toBeVisible();
  await page.screenshot({ path: "test-results/v5-executed.png" });
});

test("V5: the AI Central Bank opens up to show its floors", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("status")).toContainText("Live", { timeout: 30_000 });
  await page.getByRole("button", { name: "AI Central Bank" }).dispatchEvent("click");
  await page.getByRole("button", { name: "Go inside" }).dispatchEvent("click");
  await expect(page.getByText(/Floor 8 · Executive Dashboard/)).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText(/Vault · Secure Records Vault/)).toBeVisible();
  await page.waitForTimeout(2000);
  await page.screenshot({ path: "test-results/v5-bank-inside.png" });
});

test("dashboard frame, money game and App Lab come from the backend", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("status")).toContainText("Live", { timeout: 30_000 });
  await expect(page.getByTestId("stat-agents")).toContainText("/16");
  await expect(page.getByTestId("panel-conveyor")).toContainText("Owner");
  await expect(page.getByTestId("panel-finance")).toBeVisible();
  await page.getByRole("tab", { name: "Arena" }).click();
  await expect(page.getByTestId("leaderboard")).toContainText("Atlas");
  await expect(page.getByText("ranked by verified money")).toBeVisible();
  await page.getByRole("tab", { name: "App Lab" }).click();
  await expect(page.getByRole("button", { name: "Authorize this repository" })).toBeVisible();
});
