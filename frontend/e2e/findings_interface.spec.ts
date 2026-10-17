import { test, expect } from "@playwright/test";

test.describe("APICompass — Findings Interface & Cautious Traceability Suite", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("body")).toBeVisible();
    await expect(page.getByText("APICompass").first()).toBeVisible();
    await expect(page.getByText("Connected")).toBeVisible({ timeout: 15000 });
  });

  test("1. Cautious & Traceable Findings Card Structure on Deprecated API Call", async ({
    page,
  }) => {
    // Select Charge (Legacy Source) preset
    await page.getByRole("button", { name: "Charge (Legacy Source)" }).click();
    const runBtn = page.locator('[data-testid="run-verify-button"]');
    await runBtn.click();

    // Wait for Evidence Court Verdict
    await expect(page.getByText("Evidence Court Verdict")).toBeVisible({ timeout: 25000 });

    // Open Candidate Assessments tab where individual candidate card is rendered
    await page.getByRole("button", { name: /Candidate Assessments/i }).click();

    // Verify Candidate FindingCard exists
    const card = page.locator('[data-testid^="finding-card-"]').first();
    await expect(card).toBeVisible();

    // Verify Title is present
    const title = card.locator('[data-testid="finding-title"]');
    await expect(title).toBeVisible();
    await expect(title).toContainText(/Charge/i);

    // Verify Exact Backend Status Badge matches backend status
    const statusBadge = card.locator('[data-testid="status-badge"]');
    await expect(statusBadge).toBeVisible();
    await expect(statusBadge).toContainText("UNABLE TO VERIFY");

    // Verify Impact Classification is present (e.g. Unverified) without arbitrary severity scores
    const impactBadge = card.locator('[data-testid="impact-classification-badge"]');
    await expect(impactBadge).toBeVisible();

    // Verify Evaluated Code Fragment is rendered in monospaced code block
    const codeFrag = card.locator('[data-testid="finding-code-fragment"]');
    await expect(codeFrag).toBeVisible();
    await expect(codeFrag).toContainText("stripe.Charge.create");

    // Verify Explanation is rendered
    const explanation = card.locator('[data-testid="finding-explanation"]');
    await expect(explanation).toBeVisible();

    // Verify Interactive Jump to Line button is accessible
    const jumpBtn = card.locator('[data-testid="jump-to-line-button"]');
    await expect(jumpBtn).toBeVisible();
    await expect(jumpBtn).toHaveAttribute("aria-label", /Jump to line \d+ in editor/i);
    await jumpBtn.click();

    // Verify Propose Fix button is available
    const fixBtn = card.locator('[data-testid="propose-fix-button"]');
    await expect(fixBtn).toBeVisible();
  });

  test("2. Unverified AI Suggestions Clearly Distinguished from Confirmed Bugs", async ({
    page,
  }) => {
    // Select Charge (Legacy Source)
    await page.getByRole("button", { name: "Charge (Legacy Source)" }).click();
    await page.locator('[data-testid="run-verify-button"]').click();
    await expect(page.getByText("Evidence Court Verdict")).toBeVisible({ timeout: 25000 });

    // Switch to AI Suggestions tab
    await page.getByRole("button", { name: "AI Suggestions" }).click();

    // Verify Advisory Notice Banner states AI hypotheses are strictly unverified
    await expect(page.getByText("Advisory Hypotheses — Strictly Not Verified")).toBeVisible();
    await expect(
      page.getByText(/cannot create confirmed findings or independently alter/i)
    ).toBeVisible();

    // Verify LLM Reasoning status badge matches backend actual status
    await expect(page.getByText("disabled", { exact: true })).toBeVisible();
  });

  test("3. 'No Issue Detected' Outcome Explains Scope Limitations & Checked Constraints", async ({
    page,
  }) => {
    // Select PaymentIntent (Clean)
    await page.getByRole("button", { name: "PaymentIntent (Clean)" }).click();
    await page.locator('[data-testid="run-verify-button"]').click();
    await expect(page.getByText("Evidence Court Verdict")).toBeVisible({ timeout: 25000 });

    // In mock mode verdict panel shows mock quarantine
    await expect(page.getByText("MOCK FIXTURE QUARANTINE")).toBeVisible();

    // Switch to Candidate Assessments tab
    await page.getByRole("button", { name: /Candidate Assessments/i }).click();

    // Check candidate card is rendered
    const card = page.locator('[data-testid^="finding-card-"]').first();
    await expect(card).toBeVisible();
    await expect(card.locator('[data-testid="finding-code-fragment"]')).toContainText(
      "stripe.PaymentIntent.create"
    );
  });

  test("4. Accessible & Usable Official Source Links in Evidence Receipts", async ({ page }) => {
    await page.getByRole("button", { name: "PaymentIntent (Clean)" }).click();
    await page.locator('[data-testid="run-verify-button"]').click();
    await expect(page.getByText("Evidence Court Verdict")).toBeVisible({ timeout: 25000 });

    // Open Evidence Receipts tab
    await page.getByRole("button", { name: /Evidence Receipts/i }).click();

    // Locate official documentation link
    const docLink = page.locator('a[href*="docs.stripe.com"]').first();
    await expect(docLink).toBeVisible();

    // Verify link usability and security invariants
    await expect(docLink).toHaveAttribute("target", "_blank");
    await expect(docLink).toHaveAttribute("rel", "noopener noreferrer");

    // Verify SHA-256 excerpt fingerprint is visible
    await expect(page.getByText(/Content Hash \(SHA-256\)/i).first()).toBeVisible();
  });

  test("5. Honest Abstention on Non-API Source Code", async ({ page }) => {
    // Select Non-API (Abstain) preset
    await page.getByRole("button", { name: "Non-API (Abstain)" }).click();
    await page.locator('[data-testid="run-verify-button"]').click();
    await expect(page.getByText("Evidence Court Verdict")).toBeVisible({ timeout: 25000 });

    // Must be UNABLE TO VERIFY
    await expect(page.getByText("UNABLE TO VERIFY")).toBeVisible();

    // Must explain that zero in-scope Stripe calls were detected
    await page.getByRole("button", { name: /Candidate Assessments/i }).click();
    await expect(page.getByText("No Supported In-Scope API Calls Detected").first()).toBeVisible();
    await expect(
      page.getByText(/contains no recognizable calls to supported API ecosystem operations/i).first()
    ).toBeVisible();
  });
});

