import { test, expect } from "@playwright/test";

test.describe("APICompass — Primary Analysis Journey Suite", () => {
  test.beforeEach(async ({ page }) => {
    // Navigate to local frontend and ensure backend is healthy
    await page.goto("/");
    await expect(page.locator("body")).toBeVisible();
    await expect(page.getByText("APICompass").first()).toBeVisible();
    await expect(page.getByText("Connected")).toBeVisible({ timeout: 15000 });
  });

  test("Journey Step 1 & 2: Supported scope banner, line/character counters, and editor clear/expand controls", async ({
    page,
  }) => {
    // 1. Verify Supported Scope banner explicitly defines Python 3.x & Stripe SDK boundaries
    await expect(page.getByText("SUPPORTED SCOPE: PYTHON 3.x • STRIPE SDK")).toBeVisible();
    await expect(
      page.getByText(/Non-Stripe code is identified as out of scope without false alarms/i)
    ).toBeVisible();

    // 2. Monaco editor container is visible
    const editorContainer = page.locator('[data-testid="monaco-code-editor-container"]');
    await expect(editorContainer).toBeVisible();

    // 3. Line and character counter is rendered
    const metrics = page.locator('[data-testid="editor-metrics"]');
    await expect(metrics).toBeVisible();
    await expect(metrics).toContainText("lines");

    // 4. Test Expand / Collapse editor height toggle
    const expandBtn = page.getByRole("button", { name: /Expand/i });
    await expect(expandBtn).toBeVisible();
    await expandBtn.click();
    await expect(page.getByRole("button", { name: /Collapse/i })).toBeVisible();
    await page.getByRole("button", { name: /Collapse/i }).click();
    await expect(page.getByRole("button", { name: /Expand/i })).toBeVisible();

    // 5. Test Clear code button resets editor and clears counters
    const clearBtn = page.getByRole("button", { name: /Clear/i });
    await expect(clearBtn).toBeVisible();
    await clearBtn.click();
    await expect(metrics).toContainText("0 lines");
  });

  test("Journey Step 3 & 4: Validation for empty code and data source indicator", async ({ page }) => {
    // Clear code first
    await page.getByRole("button", { name: /Clear/i }).click();

    // Verify Data Source indicator shows Mock Fixtures in test environment
    const docSourceBadge = page.locator('[data-testid="data-source-indicator"]');
    await expect(docSourceBadge).toBeVisible();
    await expect(docSourceBadge).toContainText("Docs: Offline Mock Fixtures");

    // Attempt to start analysis with empty code
    const runBtn = page.locator('[data-testid="run-verify-button"]');
    await runBtn.click();

    // Validation alert must be displayed
    await expect(page.getByText("Source code is empty. Please enter Python code to analyze.").first()).toBeVisible();
  });

  test("Journey Step 5, 6 & 7: Streaming progress, findings inspection, line navigation, and honest abstention", async ({
    page,
  }) => {
    // Select Charge (Legacy Source) preset
    await page.getByRole("button", { name: "Charge (Legacy Source)" }).click();

    // Verify Run button has accessible label
    const runBtn = page.locator('[data-testid="run-verify-button"]');
    await expect(runBtn).toHaveAttribute("aria-label", "Start Python Stripe API Contract Analysis");
    await runBtn.click();

    // Step 5: Real streaming progress appears
    const progress = page.locator('[data-testid="live-scan-progress"]');
    await expect(progress).toBeVisible();
    await expect(progress.getByText("Accepted")).toBeVisible();

    // Wait for Evidence Court Verdict
    await expect(page.getByText("Evidence Court Verdict")).toBeVisible({ timeout: 25000 });

    // Step 7: In mock mode, verdict is quarantined as UNABLE TO VERIFY
    await expect(page.getByText("UNABLE TO VERIFY")).toBeVisible();
    await expect(page.getByText("MOCK FIXTURE QUARANTINE")).toBeVisible();

    // Honest Abstention Breakdown must be presented explaining mock quarantine
    await expect(page.getByText(/Why did APICompass abstain from a definitive verdict\?/i)).toBeVisible();
    await expect(page.getByText("Mock Mode Active:")).toBeVisible();
    await expect(page.getByText(/stripe\.Charge\.create/i).first()).toBeVisible();

    // Step 6: Evidence receipts inspection
    await page.getByRole("button", { name: /Evidence Receipts/i }).click();
    await expect(page.getByText(/docs\.stripe\.com/i).first()).toBeVisible();
    await expect(page.getByText(/MOCK FIXTURE \(OFFLINE\)/i).first()).toBeVisible();

    // Candidate Assessments tab
    await page.getByRole("button", { name: /Candidate Assessments/i }).click();
    await expect(page.getByText("stripe.Charge.create").first()).toBeVisible();

    // Check jump-to-line button exists
    const lineJumpBtn = page.getByRole("button", { name: /Line \d+/i }).first();
    await expect(lineJumpBtn).toBeVisible();
    await lineJumpBtn.click();
  });

  test("Journey Step 8: Code modification tracking, warning banner, and re-analysis flow", async ({ page }) => {
    // Select PaymentIntent (Clean)
    await page.getByRole("button", { name: "PaymentIntent (Clean)" }).click();
    const runBtn = page.locator('[data-testid="run-verify-button"]');
    await runBtn.click();

    // Await first analysis completion
    await expect(page.getByText("Evidence Court Verdict")).toBeVisible({ timeout: 25000 });

    // Focus Monaco editor and type to modify code
    const monacoTextarea = page.getByRole("textbox", { name: "Editor content" });
    await monacoTextarea.focus();
    await page.keyboard.type("# modifying code after analysis\n");

    // Warning banner must be visible informing developer results are stale
    await expect(page.getByText(/Editor modified since last analysis/i)).toBeVisible();
    await expect(page.getByText(/The results below reflect the previous code/i)).toBeVisible();

    // Action button updates text to Re-Analyze Code
    await expect(page.getByRole("button", { name: /Re-Analyze Code/i }).first()).toBeVisible();

    // Click Re-Analyze Code button in the banner
    const reanalyzeBtn = page.getByRole("button", { name: /Re-Analyze Code/i }).first();
    await reanalyzeBtn.click();

    // New analysis runs and banner clears once results refresh
    await expect(page.getByText("Evidence Court Verdict")).toBeVisible({ timeout: 25000 });
    await expect(page.getByText(/Editor modified since last analysis/i)).not.toBeVisible();
  });

  test("Syntax error handling: Clean halt without code execution", async ({ page }) => {
    // Select Syntax Error preset
    await page.getByRole("button", { name: "Syntax Error" }).click();
    const runBtn = page.locator('[data-testid="run-verify-button"]');
    await runBtn.click();

    // Syntax error banner must appear
    await expect(page.getByText("Python Syntax Error Detected")).toBeVisible({ timeout: 20000 });
    await expect(
      page.getByText(/Analysis was halted cleanly because invalid syntax cannot be parsed into an AST/i)
    ).toBeVisible();
  });

  test("Journey Step 9, 10 & 11: Fix Proposal lifecycle (Discard vs Apply), zero silent overwrite, and Severity Filter", async ({
    page,
  }) => {
    // Select Charge (Legacy Source) preset which produces findings
    await page.getByRole("button", { name: "Charge (Legacy Source)" }).click();
    const runBtn = page.locator('[data-testid="run-verify-button"]');
    await runBtn.click();

    // Wait for Evidence Court Verdict
    await expect(page.getByText("Evidence Court Verdict")).toBeVisible({ timeout: 25000 });

    // In Candidate Assessments, verify findings filter bar is rendered
    await page.getByRole("button", { name: /Candidate Assessments/i }).click();

    // Verify findings filter bar is rendered
    const filterBar = page.locator('[data-testid="findings-filter-bar"]');
    await expect(filterBar).toBeVisible();
    await expect(page.locator('[data-testid="filter-all-button"]')).toBeVisible();
    await expect(page.locator('[data-testid="filter-error-button"]')).toBeVisible();
    await expect(page.locator('[data-testid="filter-warning-button"]')).toBeVisible();

    // Test clicking filter buttons
    await page.locator('[data-testid="filter-error-button"]').click();
    // Verify filter can be toggled back
    await page.locator('[data-testid="filter-all-button"]').click();

    // Trigger fix proposal
    const proposeBtn = page.locator('[data-testid="propose-fix-button"]').first();
    await expect(proposeBtn).toBeVisible();
    await proposeBtn.click();

    // Wait for Fix Proposal tab to be selected and diff viewer to render
    await expect(page.getByRole("button", { name: /Fix Proposal/i })).toBeVisible();
    await expect(page.locator('[data-testid="diff-view"]')).toBeVisible({ timeout: 25000 });

    // Verify Discard Fix button exists with accessible label
    const discardBtn = page.locator('[data-testid="discard-fix-button"]');
    await expect(discardBtn).toBeVisible();
    await expect(discardBtn).toHaveAttribute(
      "aria-label",
      "Discard proposed fix and preserve original code"
    );

    // Click Discard Fix: code must NOT be modified, notice must be displayed, returns to verdict tab
    await discardBtn.click();
    await expect(
      page.getByText("Fix proposal discarded. Original code was preserved without changes.")
    ).toBeVisible();

    // Open Candidate Assessments again and re-trigger fix proposal
    await page.getByRole("button", { name: /Candidate Assessments/i }).click();
    await page.locator('[data-testid="propose-fix-button"]').first().click();
    await expect(page.locator('[data-testid="diff-view"]')).toBeVisible({ timeout: 25000 });

    // Verify Apply Fix button exists with accessible label
    const applyBtn = page.locator('[data-testid="apply-fix-button"]');
    await expect(applyBtn).toBeVisible();
    await expect(applyBtn).toHaveAttribute("aria-label", "Apply proposed fix directly to editor");

    // Click Apply Fix: code in editor updates, banner displays, tab returns to verdict
    await applyBtn.click();
    await expect(
      page.getByText(/Proposed fix applied to editor\. Click 'Re-Analyze Code'/i)
    ).toBeVisible();

    // Editor modified warning must be displayed
    await expect(page.getByText(/Editor modified since last analysis/i)).toBeVisible();

    // Click Re-Analyze Code to verify the fix
    const reanalyzeBtn = page.getByRole("button", { name: /Re-Analyze Code/i }).first();
    await expect(reanalyzeBtn).toBeVisible();
    await reanalyzeBtn.click();

    // New analysis finishes cleanly
    await expect(page.getByText("Evidence Court Verdict")).toBeVisible({ timeout: 25000 });
  });
});
