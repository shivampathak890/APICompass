import { test, expect } from "@playwright/test";

test.describe("APICompass v3 — Trust, Provenance & Transparency Suite", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("body")).toBeVisible();
    await expect(page.getByText("APICompass").first()).toBeVisible();
    await expect(page.getByText("Connected")).toBeVisible({ timeout: 15000 });
  });

  test("1. Provider status is displayed honestly with unverified connectivity caveats", async ({ page }) => {
    // Verify provider status section in footer
    await expect(page.getByText("External Providers:")).toBeVisible();
    // In mock mode without keys, TinyFish should display "Disabled" or "Missing Credentials"
    const footer = page.locator("footer");
    await expect(footer).toContainText(/TinyFish Docs:/i);
    await expect(footer).toContainText(/LLM Reasoning:/i);
    await expect(footer).toContainText(
      /Configured.*indicates credentials are set, not that upstream connectivity is verified/i
    );
  });

  test("2. Verification Studio displays explicit verdict semantics, scope metrics, and mock quarantine", async ({
    page,
  }) => {
    // Select Charge (Legacy Source)
    await page.getByRole("button", { name: "Charge (Legacy Source)" }).click();

    // Run verification
    const verifyBtn = page.locator('[data-testid="run-verify-button"]');
    await verifyBtn.click();

    // Wait for Evidence Court Verdict panel
    await expect(page.getByText("Evidence Court Verdict")).toBeVisible({ timeout: 15000 });

    // In mock mode, verdict must be UNABLE TO VERIFY (ABSTAINED) with MOCK FIXTURE QUARANTINE
    await expect(page.getByText(/UNABLE TO VERIFY/i)).toBeVisible();
    await expect(page.getByText("MOCK FIXTURE QUARANTINE")).toBeVisible();

    // Scope transparency must be displayed
    await expect(page.getByText("Analysis Scope:")).toBeVisible();
    await expect(page.getByText(/lines analyzed/i)).toBeVisible();
    await expect(page.getByText(/API candidate\(s\) examined/i)).toBeVisible();

    // Plain-language verdict definition must explain abstention
    await expect(page.getByText("Plain Meaning:")).toBeVisible();
    await expect(
      page.getByText(/Evidence Court abstained from issuing a definitive verdict/i)
    ).toBeVisible();
  });

  test("3. Evidence Receipts tab displays live/mock status, version, and excerpt fingerprint disclaimer", async ({
    page,
  }) => {
    // Select PaymentIntent (Clean)
    await page.getByRole("button", { name: "PaymentIntent (Clean)" }).click();
    await page.locator('[data-testid="run-verify-button"]').click();

    // Wait for Evidence Court Verdict
    await expect(page.getByText("Evidence Court Verdict")).toBeVisible({ timeout: 15000 });

    // Click Evidence Receipts tab
    await page.getByRole("button", { name: /Evidence Receipts/i }).click();

    // Check mock fixture badge is visible
    await expect(page.getByText("MOCK FIXTURE (OFFLINE)").first()).toBeVisible();

    // Check excerpt fingerprint explanation
    await expect(
      page.getByText(/Content Hash \(SHA-256\): Evaluated text snippet fingerprint/i).first()
    ).toBeVisible();
    await expect(
      page.getByText(/proves content identity, not publisher authenticity or tamper-proof storage/i).first()
    ).toBeVisible();

    // Check safe link (has target="_blank")
    const docLink = page.locator('a[href*="docs.stripe.com"]').first();
    await expect(docLink).toHaveAttribute("target", "_blank");
    await expect(docLink).toHaveAttribute("rel", "noopener noreferrer");
  });

  test("4. AI Suggestions tab clearly separates non-verified hypotheses from deterministic findings", async ({
    page,
  }) => {
    // Select Charge (Legacy Source)
    await page.getByRole("button", { name: "Charge (Legacy Source)" }).click();
    await page.locator('[data-testid="run-verify-button"]').click();

    // Wait for report
    await expect(page.getByText("Evidence Court Verdict")).toBeVisible({ timeout: 15000 });

    // Click AI Suggestions tab
    await page.getByRole("button", { name: "AI Suggestions" }).click();

    // Advisory notice banner must be visible
    await expect(page.getByText("Advisory Hypotheses — Strictly Not Verified")).toBeVisible();
    await expect(
      page.getByText(/AI suggestions analyze static API candidate patterns against expected conventions/i)
    ).toBeVisible();
    await expect(
      page.getByText(/CANNOT create confirmed findings or independently alter Evidence Court verdicts/i)
    ).toBeVisible();
  });

  test("5. Fix Proposals display syntax validation caveat and user review notice", async ({
    page,
  }) => {
    // Select Charge (Legacy Source) and verify
    await page.getByRole("button", { name: "Charge (Legacy Source)" }).click();
    await page.locator('[data-testid="run-verify-button"]').click();
    await expect(page.getByText("Evidence Court Verdict")).toBeVisible({ timeout: 15000 });

    // Open Candidate Assessments tab and click Fix
    await page.getByRole("button", { name: /Candidate Assessments/i }).click();
    const fixBtn = page.locator('[data-testid="propose-fix-button"]').first();
    await expect(fixBtn).toBeVisible();
    await fixBtn.click();

    // Fix proposal panel should appear
    await expect(page.getByText("Static Re-Verification Assessment")).toBeVisible({ timeout: 15000 });

    // Syntax validation caveat must be visible
    await expect(page.getByText("Syntax Caveat:")).toBeVisible();
    await expect(
      page.getByText(/Valid syntax confirms that proposed code parses into a Python AST. It does NOT prove runtime correctness/i)
    ).toBeVisible();

    // User review notice must be visible
    await expect(
      page.getByText(/Local files are never automatically modified/i)
    ).toBeVisible();
  });

  test("6. Scan History explains source fingerprint privacy and local database integrity limits", async ({
    page,
  }) => {
    // Open Scan History view
    await page.getByRole("button", { name: "Scan Audit History" }).click();
    await expect(page.getByText("SQLite Scan Audit Repository")).toBeVisible();

    // Click Inspect on first record
    const inspectBtn = page.getByRole("button", { name: "Inspect" }).first();
    await expect(inspectBtn).toBeVisible({ timeout: 10000 });
    await inspectBtn.click();

    // Detail panel open
    await expect(page.getByText("Historical Audit Snapshot")).toBeVisible();
    await expect(
      page.getByText(/This is a stored audit snapshot reflecting evidence evaluated at that time/i)
    ).toBeVisible();

    // Source fingerprint privacy explanation
    await expect(
      page.getByText(/Privacy: raw source retention disabled/i)
    ).toBeVisible();

    // Record integrity hash limitations (not tamper-proof/blockchain)
    await expect(
      page.getByText(/A locally stored hash does not provide tamper-proof immutability/i)
    ).toBeVisible();
  });

  test("7. Multi-File Project analysis displays incomplete analysis warning when syntax errors exist", async ({
    page,
  }) => {
    // Navigate to Multi-File Project view
    await page.locator('[data-testid="nav-tab-project"]').click();
    await expect(page.getByText("Multi-File Project").first()).toBeVisible();

    // Click "Syntax Error" preset
    await page.getByRole("button", { name: "Syntax Error" }).click();

    // Click Analyze Project
    await page.locator('[data-testid="analyze-project-button"]').click();

    // Wait for project analysis result
    await expect(page.getByText("Project Verdict", { exact: true })).toBeVisible({ timeout: 15000 });

    // Incomplete analysis warning should be displayed
    await expect(page.getByText(/Incomplete Analysis Warning:/i)).toBeVisible();
    await expect(
      page.getByText(/failed syntax parsing/i)
    ).toBeVisible();
    await expect(
      page.getByText(/cannot certify absence of issues in unparsed files/i)
    ).toBeVisible();
  });
});
