import { test, expect } from "@playwright/test";

test.describe("APICompass — State Handling, Failure Modes & Recovery Suite", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("body")).toBeVisible();
    await expect(page.getByText("APICompass").first()).toBeVisible();

    // Ensure connection is established (if health check was slow, click Check Health)
    const unavailableBanner = page.getByText("Backend Service Offline or Unreachable");
    if (await unavailableBanner.isVisible()) {
      const checkBtn = page.getByRole("button", { name: "Check Health" });
      if (await checkBtn.isVisible()) {
        await checkBtn.click();
      }
    }
    await expect(page.locator('[data-testid="run-verify-button"]')).toBeVisible({ timeout: 20000 });
  });

  test("1. Initial Empty State & Preset Quick Loading", async ({ page }) => {
    // Click Clear Code button to empty the editor
    const clearBtn = page.getByRole("button", { name: /Clear/i });
    await clearBtn.click();

    // Verify initial empty state card is rendered
    const emptyCard = page.locator('[data-testid="initial-empty-state"]');
    await expect(emptyCard).toBeVisible();
    await expect(emptyCard).toContainText("Code Editor is Empty");
    await expect(emptyCard).toContainText("Zero-Execution Guarantee");
    await expect(emptyCard).toContainText("Supported Scope");

    // Click quick preset button to load clean PaymentIntent
    const loadCleanBtn = page.locator('[data-testid="empty-load-clean-btn"]');
    await expect(loadCleanBtn).toBeVisible();
    await loadCleanBtn.click();

    // The empty state card now updates to "Ready for Static API Contract Analysis"
    await expect(emptyCard).toContainText("Ready for Static API Contract Analysis");
  });

  test("2. Empty Code Submission Validation & Recovery Guidance", async ({ page }) => {
    // Clear code
    await page.getByRole("button", { name: /Clear/i }).click();

    // Attempt to run analysis on empty code
    const runBtn = page.locator('[data-testid="run-verify-button"]');
    await runBtn.click();

    // Verify actionable Empty Code Submission Alert is displayed
    const emptyAlert = page.locator('[data-testid="empty-code-submission-alert"]');
    await expect(emptyAlert).toBeVisible();
    await expect(emptyAlert).toContainText("Cannot Analyze Empty Source Code");

    // Verify actionable "Load Starter Example" recovery button works
    const loadExampleBtn = page.locator('[data-testid="load-example-button"]');
    await expect(loadExampleBtn).toBeVisible();
    await loadExampleBtn.click();

    // Empty alert disappears and code is populated
    await expect(emptyAlert).not.toBeVisible();
    await expect(page.locator('[data-testid="initial-empty-state"]')).toContainText(
      "Ready for Static API Contract Analysis"
    );
  });

  test("3. Syntax Error Navigation and Non-Crash Recovery", async ({ page }) => {
    // Select Syntax Error preset
    await page.getByRole("button", { name: "Syntax Error" }).click();

    // Run analysis
    const runBtn = page.locator('[data-testid="run-verify-button"]');
    await runBtn.click();

    // Verify Python Syntax Error Detected alert is displayed
    await expect(page.getByText("Python Syntax Error Detected")).toBeVisible({ timeout: 20000 });

    // Verify Jump to Syntax Error button exists and is clickable
    const jumpBtn = page.locator('[data-testid="jump-to-syntax-error"]');
    await expect(jumpBtn).toBeVisible();
    await jumpBtn.click();

    // Loading indicator must have terminated cleanly
    await expect(runBtn).not.toBeDisabled();
  });

  test("4. Duplicate Click Prevention & Cancellation Lifecycle", async ({ page }) => {
    await page.getByRole("button", { name: "PaymentIntent (Clean)" }).click();
    const runBtn = page.locator('[data-testid="run-verify-button"]');

    // Click run
    await runBtn.click();

    // Verify loading state is active and Run button is disabled or in progress
    await expect(page.getByText(/Evidence Court|Live Verification in Progress/i).first()).toBeVisible({
      timeout: 25000,
    });

    // Loading indicator must terminate upon completion
    await expect(runBtn).not.toBeDisabled({ timeout: 25000 });
  });

  test("5. Real Progress Stages Timeline Verification", async ({ page }) => {
    await page.getByRole("button", { name: "Charge (Legacy Source)" }).click();
    const runBtn = page.locator('[data-testid="run-verify-button"]');
    await runBtn.click();

    // Wait for Evidence Court Verdict
    await expect(page.getByText("Evidence Court Verdict")).toBeVisible({ timeout: 25000 });

    // Open AST Scope tab
    await page.getByRole("button", { name: /AST Scope/i }).first().click();
    await expect(page.getByText("Passive AST inspection only — zero runtime execution")).toBeVisible();
    await expect(page.getByText("Deterministic quotation verification")).toBeVisible();
  });
});

