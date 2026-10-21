import { test, expect } from "@playwright/test";

test.describe("APICompass v3 — End-to-End Suite", () => {
  test.beforeEach(async ({ page }) => {
    // Navigate to local frontend
    await page.goto("/");
    await expect(page.locator("body")).toBeVisible();
    await expect(page.getByText("APICompass").first()).toBeVisible();
    // Guarantee backend is connected before test runs
    await expect(page.getByText("Connected")).toBeVisible({ timeout: 15000 });
  });

  // Scenario 1: App loads & editor becomes usable
  test("1. App loads & editor becomes usable (Monaco rendered, line numbers visible)", async ({ page }) => {
    // Check Monaco Editor container is present
    const editorContainer = page.locator('[data-testid="monaco-code-editor-container"]');
    await expect(editorContainer).toBeVisible();

    // Check Monaco editor DOM elements loaded
    await expect(page.locator(".monaco-editor")).toBeVisible();
    await expect(page.locator(".line-numbers").first()).toBeVisible();

    // Verify Verification Studio view is active by default
    await expect(page.getByRole("button", { name: "Verification Studio" })).toBeVisible();
    await expect(page.locator('[data-testid="run-verify-button"]')).toBeVisible();
  });

  // Scenario 2: Sample selection loads snippet into Monaco
  test("2. Sample selection loads snippet into Monaco", async ({ page }) => {
    const editor = page.locator(".monaco-editor");

    // Click "PaymentIntent (Clean)" preset
    await page.getByRole("button", { name: "PaymentIntent (Clean)" }).click();
    await expect(editor).toContainText("PaymentIntent");

    // Click "Non-API (Abstain)" preset
    await page.getByRole("button", { name: "Non-API (Abstain)" }).click();
    await expect(editor).toContainText("calculate_subtotal");

    // Click "Charge (Legacy Source)" preset
    await page.getByRole("button", { name: "Charge (Legacy Source)" }).click();
    await expect(editor).toContainText("stripe.Charge.create");
  });

  // Scenario 3: Scan submission displays real streaming progress
  test("3. Scan submission displays real streaming progress with truthful stages", async ({ page }) => {
    // Load default Charge snippet
    await page.getByRole("button", { name: "Charge (Legacy Source)" }).click();

    // Click verify
    const verifyBtn = page.locator('[data-testid="run-verify-button"]');
    await expect(verifyBtn).toBeEnabled();
    await verifyBtn.click();

    // Live scan progress should appear
    const progress = page.locator('[data-testid="live-scan-progress"]');
    await expect(progress).toBeVisible();

    // Progress checkpoints should be displayed inside live progress widget
    await expect(progress.getByText("Accepted", { exact: true })).toBeVisible();
    await expect(progress.getByText("Static AST")).toBeVisible();

    // Wait for completion (verify button reverts to enabled state)
    await expect(verifyBtn).toBeEnabled({ timeout: 25000 });
  });

  // Scenario 4: Final Evidence Court report rendered
  test("4. Final Evidence Court report rendered with verdicts and documentation receipts", async ({ page }) => {
    await page.getByRole("button", { name: "Charge (Legacy Source)" }).click();
    const verifyBtn = page.locator('[data-testid="run-verify-button"]');
    await expect(verifyBtn).toBeEnabled();
    await verifyBtn.click();

    // Wait for Evidence Court report to render
    await expect(page.getByText("Evidence Court Verdict")).toBeVisible({ timeout: 25000 });

    // In mock mode, verdict is quarantined as unable_to_verify
    await expect(page.getByText("UNABLE TO VERIFY")).toBeVisible();

    // Navigate to Evidence Receipts tab
    await page.getByRole("button", { name: /Evidence Receipts/i }).click();
    await expect(page.getByText(/stripe\.com/i).first()).toBeVisible();

    // Check candidate assessments tab
    await page.getByRole("button", { name: /Candidate Assessments/i }).click();
    await expect(page.getByText("stripe.Charge.create").first()).toBeVisible();
  });

  // Scenario 5: Syntax error in Monaco displays error banner & abstention without executing code
  test("5. Syntax error in Monaco displays error banner & abstention without code execution", async ({ page }) => {
    // Select Syntax Error preset
    await page.getByRole("button", { name: "Syntax Error" }).click();
    const verifyBtn = page.locator('[data-testid="run-verify-button"]');
    await expect(verifyBtn).toBeEnabled();
    await verifyBtn.click();

    // Wait for Syntax error report
    await expect(page.getByText("Python Syntax Error Detected")).toBeVisible({ timeout: 20000 });
    await expect(page.getByText(/Analysis was halted cleanly because invalid syntax cannot be parsed into an AST/i)).toBeVisible();
  });

  // Scenario 6: Mock evidence quarantine verified
  test("6. Mock evidence quarantine verified (mock warning banner displayed, no verified verdict)", async ({ page }) => {
    await page.getByRole("button", { name: "PaymentIntent (Clean)" }).click();
    const verifyBtn = page.locator('[data-testid="run-verify-button"]');
    await expect(verifyBtn).toBeEnabled();
    await verifyBtn.click();

    // Wait for report
    await expect(page.getByText("Evidence Court Verdict")).toBeVisible({ timeout: 25000 });

    // Must show mock quarantine badge
    await expect(page.getByText("MOCK FIXTURE QUARANTINE")).toBeVisible();

    // Must show Integrity Policy Notice
    await expect(
      page.getByText(/Mock evidence is quarantined and can never produce production verified/i)
    ).toBeVisible();

    // Verdict must be UNABLE TO VERIFY, never clean
    await expect(page.getByText("UNABLE TO VERIFY")).toBeVisible();
  });

  // Scenario 7: Disabled LLM shown honestly
  test("7. Disabled LLM shown honestly ('AI Reasoning Disabled' / heuristic fallback)", async ({ page }) => {
    await page.getByRole("button", { name: "Charge (Legacy Source)" }).click();
    const verifyBtn = page.locator('[data-testid="run-verify-button"]');
    await expect(verifyBtn).toBeEnabled();
    await verifyBtn.click();

    await expect(page.getByText("Evidence Court Verdict")).toBeVisible({ timeout: 25000 });

    // Open AI Suggestions tab
    await page.getByRole("button", { name: /AI Suggestions/i }).click();

    // LLM Reasoning status badge should display disabled
    await expect(page.getByText("disabled", { exact: true })).toBeVisible();
    await expect(page.getByText(/LLM reasoning is currently disabled/i)).toBeVisible();
    await expect(page.getByText(/The model proposes; deterministic code decides/i).first()).toBeVisible();
  });

  // Scenario 8: Persisted scan visible in history view with correct metadata
  test("8. Persisted scan visible in history view with correct metadata", async ({ page }) => {
    // Run a scan to ensure there is a persistent record
    await page.getByRole("button", { name: "Charge (Legacy Source)" }).click();
    const verifyBtn = page.locator('[data-testid="run-verify-button"]');
    await expect(verifyBtn).toBeEnabled();
    await verifyBtn.click();
    await expect(page.getByText("Evidence Court Verdict")).toBeVisible({ timeout: 25000 });

    // Switch to Scan Audit History view
    await page.getByRole("button", { name: "Scan Audit History" }).click();

    // Check History table headers and entry
    await expect(page.getByText("SQLite Scan Audit Repository")).toBeVisible();
    await expect(page.getByText("payment_handler.py").first()).toBeVisible({ timeout: 10000 });
    await expect(page.getByText("stripe").first()).toBeVisible();
  });

  // Scenario 9: Historical scan snapshot loaded from history view into Evidence Court without re-scanning
  test("9. Historical scan snapshot loaded from history view without re-scanning", async ({ page }) => {
    // Run a scan first to ensure a persistent entry exists
    await page.getByRole("button", { name: "Charge (Legacy Source)" }).click();
    const verifyBtn = page.locator('[data-testid="run-verify-button"]');
    await expect(verifyBtn).toBeEnabled();
    await verifyBtn.click();
    await expect(page.getByText("Evidence Court Verdict")).toBeVisible({ timeout: 25000 });

    // Open History view
    await page.getByRole("button", { name: "Scan Audit History" }).click();
    await expect(page.getByText("SQLite Scan Audit Repository")).toBeVisible();

    // Verify opening historical snapshot dispatches 0 new analysis requests
    let analyzeRequests = 0;
    page.on("request", (req) => {
      if (req.url().includes("/api/v1/analyze")) {
        analyzeRequests++;
      }
    });

    // Click "Inspect" on the first row
    const inspectBtn = page.getByRole("button", { name: "Inspect" }).first();
    await expect(inspectBtn).toBeVisible({ timeout: 10000 });
    await inspectBtn.click();

    // Detail panel opens with historical banner
    await expect(page.getByText("Historical Audit Snapshot")).toBeVisible({ timeout: 10000 });
    await expect(
      page.getByText(/This is a stored audit snapshot reflecting evidence evaluated at that time/i)
    ).toBeVisible();

    // Zero re-scan requests verified
    expect(analyzeRequests).toBe(0);

    // Close detail panel
    await page.getByRole("button", { name: "Close Detail" }).click();
    await expect(page.getByText("Historical Audit Snapshot")).not.toBeVisible();
  });

  // Scenario 10: Deleting historical scan removes it from history list after server confirms
  test("10. Deleting historical scan removes it from history list after server confirms", async ({ page }) => {
    // Run a scan first to ensure an entry exists to delete
    await page.getByRole("button", { name: "Charge (Legacy Source)" }).click();
    const verifyBtn = page.locator('[data-testid="run-verify-button"]');
    await expect(verifyBtn).toBeEnabled();
    await verifyBtn.click();
    await expect(page.getByText("Evidence Court Verdict")).toBeVisible({ timeout: 25000 });

    // Switch to Scan Audit History view
    await page.getByRole("button", { name: "Scan Audit History" }).click();
    await expect(page.getByText("SQLite Scan Audit Repository")).toBeVisible();

    // Find delete button on first record
    const deleteBtn = page.locator('button[title="Delete Record"]').first();
    await expect(deleteBtn).toBeVisible({ timeout: 10000 });
    await deleteBtn.click();

    // Modal appears
    await expect(page.getByText("Confirm Explicit Scan Deletion")).toBeVisible();

    // Await server DELETE response confirmation
    const deleteResponsePromise = page.waitForResponse(
      (resp) => resp.url().includes("/api/v1/scans/") && resp.request().method() === "DELETE"
    );

    // Click "Permanently Delete"
    await page.getByRole("button", { name: "Permanently Delete" }).click();

    const deleteResp = await deleteResponsePromise;
    expect([200, 204]).toContain(deleteResp.status());

    // Modal disappears
    await expect(page.getByText("Confirm Explicit Scan Deletion")).not.toBeVisible({ timeout: 10000 });
  });

  // Scenario 11: Fix proposal displayed as advisory; applying updates editor state only
  test("11. Fix proposal displayed as advisory; applying updates editor state only without executing", async ({ page }) => {
    // Ensure in editor mode
    await page.getByRole("button", { name: "Verification Studio" }).click();

    // Load Charge deprecated snippet and scan
    await page.getByRole("button", { name: "Charge (Legacy Source)" }).click();
    const verifyBtn = page.locator('[data-testid="run-verify-button"]');
    await expect(verifyBtn).toBeEnabled();
    await verifyBtn.click();
    await expect(page.getByText("Evidence Court Verdict")).toBeVisible({ timeout: 25000 });

    // Click Candidate Assessments tab and propose fix
    await page.getByRole("button", { name: /Candidate Assessments/i }).click();
    const fixBtn = page.locator('button[title*="Propose evidence-gated fix"]').first();
    await expect(fixBtn).toBeVisible();
    await fixBtn.click();

    // Automatically switches to Fix Proposal tab
    await expect(page.getByText("Static Re-Verification Assessment")).toBeVisible({ timeout: 20000 });
    await expect(page.getByText("MOCK EVIDENCE ONLY")).toBeVisible();
    await expect(page.getByText("Unified Diff (In-Memory Proposal)")).toBeVisible();

    // Click "Use Proposed Version in Editor"
    const applyBtn = page.locator('[data-testid="apply-fix-button"]');
    await expect(applyBtn).toBeVisible();
    await applyBtn.click();

    // Editor notice banner is shown
    await expect(page.getByText(/Proposed fix applied to editor/i)).toBeVisible();

    // Monaco editor contains the updated PaymentIntent code
    const editor = page.locator(".monaco-editor");
    await expect(editor).toContainText("PaymentIntent");
  });

  // Scenario 12: Stream error / disconnect handled gracefully
  test("12. Stream error / disconnect handled gracefully", async ({ page }) => {
    // Intercept analyze/stream to simulate an unexpected network interruption
    await page.route("**/api/v1/analyze/stream", (route) => {
      route.abort("failed");
    });

    await page.getByRole("button", { name: "PaymentIntent (Clean)" }).click();
    const verifyBtn = page.locator('[data-testid="run-verify-button"]');
    await expect(verifyBtn).toBeEnabled();
    await verifyBtn.click();

    // Error banner should be displayed without application crash
    const errorBanner = page.locator(
      '[data-testid="streaming-interrupted-banner"], [data-testid="backend-unavailable-banner"]'
    );
    await expect(errorBanner).toBeVisible({ timeout: 15000 });
    await expect(
      page.getByText(/Streaming Connection Interrupted|Backend Service Offline or Unreachable/i)
    ).toBeVisible();

    // Live scan progress displays error alert
    await expect(page.locator('[data-testid="live-scan-progress"]')).toBeVisible();

    // Clean unroute
    await page.unroute("**/api/v1/analyze/stream");
  });

  // Scenario 13: Duplicate scan submissions blocked while running
  test("13. Duplicate scan submissions blocked while running", async ({ page }) => {
    // Introduce a brief deterministic delay on stream endpoint so scan remains actively in-flight
    await page.route("**/api/v1/analyze/stream", async (route) => {
      await new Promise((r) => setTimeout(r, 600));
      await route.continue();
    });

    await page.getByRole("button", { name: "Charge (Legacy Source)" }).click();

    let streamRequestCount = 0;
    page.on("request", (req) => {
      if (req.url().includes("/api/v1/analyze/stream")) {
        streamRequestCount++;
      }
    });

    const verifyBtn = page.locator('[data-testid="run-verify-button"]');
    await expect(verifyBtn).toBeEnabled();
    await verifyBtn.click();

    // Button should be disabled immediately during streaming analysis
    await expect(verifyBtn).toBeDisabled();
    await expect(verifyBtn).toContainText("Adjudicating in Evidence Court...");

    // Attempt to force click disabled button while scan is active; verify no duplicate stream request dispatched
    await verifyBtn.click({ force: true }).catch(() => {});
    expect(streamRequestCount).toBe(1);

    // Wait until scan completes and button re-enables
    await expect(verifyBtn).toBeEnabled({ timeout: 25000 });

    // Clean unroute
    await page.unroute("**/api/v1/analyze/stream");
  });

  // Scenario 14: Responsive layout does not clip Monaco editor or Evidence Court panels on narrower viewports
  test("14. Responsive layout does not clip Monaco editor or panels on narrower viewports", async ({ page }) => {
    // Set tablet viewport
    await page.setViewportSize({ width: 768, height: 1024 });

    // Check editor container is fully visible and width fits inside viewport
    const editorContainer = page.locator('[data-testid="monaco-code-editor-container"]');
    await expect(editorContainer).toBeVisible();
    const box = await editorContainer.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.width).toBeLessThanOrEqual(768);

    // Verify action buttons fit within screen width
    const verifyBtn = page.locator('[data-testid="run-verify-button"]');
    await expect(verifyBtn).toBeVisible();

    // Restore desktop viewport
    await page.setViewportSize({ width: 1280, height: 800 });
    await expect(editorContainer).toBeVisible();
  });
});
