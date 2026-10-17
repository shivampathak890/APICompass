import { test, expect } from "@playwright/test";

test.describe("APICompass v3 — Multi-File Project Analysis Suite", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("body")).toBeVisible();
    await expect(page.getByText("APICompass").first()).toBeVisible();
    // Ensure backend is connected
    await expect(page.getByText("Connected")).toBeVisible({ timeout: 15000 });
  });

  test("1. Navigation to Multi-File Project view renders editor, tabs, and presets", async ({ page }) => {
    // Click navigation tab for Multi-File Project
    const projectTab = page.locator('[data-testid="nav-tab-project"]');
    await expect(projectTab).toBeVisible();
    await projectTab.click();

    // Verify Project View is active
    await expect(page.getByText("Multi-File Project").first()).toBeVisible();
    await expect(page.getByText("Zero Execution Guarantee").first()).toBeVisible();

    // Check default files are loaded (Preset: Stripe Migration)
    await expect(page.getByRole("button", { name: "main.py" })).toBeVisible();
    await expect(page.getByRole("button", { name: "services/payment.py" })).toBeVisible();

    // Verify Monaco editor is rendered
    await expect(page.locator(".monaco-editor")).toBeVisible();
    await expect(page.getByText("Editing: main.py")).toBeVisible();

    // Verify presets are available
    await expect(page.getByRole("button", { name: "Stripe Migration" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Clean Intent" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Circular" })).toBeVisible();

    // Verify Analyze Project button is present and enabled
    const analyzeBtn = page.locator('[data-testid="analyze-project-button"]');
    await expect(analyzeBtn).toBeVisible();
    await expect(analyzeBtn).toBeEnabled();
  });

  test("2. Add new file and switch between file tabs in project editor", async ({ page }) => {
    // Switch to Multi-File Project view
    await page.locator('[data-testid="nav-tab-project"]').click();

    // Click "New File" button
    const newFileOpenBtn = page.locator('[data-testid="new-file-open-btn"]');
    await expect(newFileOpenBtn).toBeVisible();
    await newFileOpenBtn.click();

    // Input new file path
    const fileInput = page.locator('[data-testid="new-file-input"]');
    await expect(fileInput).toBeVisible();
    await fileInput.fill("utils/tax_calc.py");

    // Click "Add" button
    const addBtn = page.locator('[data-testid="add-file-btn"]');
    await addBtn.click();

    // Verify the new file tab is present and selected
    await expect(page.getByRole("button", { name: "utils/tax_calc.py" })).toBeVisible();
    await expect(page.getByText("Editing: utils/tax_calc.py")).toBeVisible();

    // Switch back to "services/payment.py"
    await page.getByRole("button", { name: "services/payment.py" }).click();
    await expect(page.getByText("Editing: services/payment.py")).toBeVisible();

    // Switch back to "main.py"
    await page.getByRole("button", { name: "main.py" }).click();
    await expect(page.getByText("Editing: main.py")).toBeVisible();
  });

  test("3. Run multi-file project analysis and verify project summary & dependency graph", async ({ page }) => {
    // Switch to Multi-File Project view
    await page.locator('[data-testid="nav-tab-project"]').click();

    // Ensure we have the Stripe Migration preset loaded
    await page.getByRole("button", { name: "Stripe Migration" }).click();
    await expect(page.getByText("Editing: main.py")).toBeVisible();

    // Click "Analyze Project"
    const analyzeBtn = page.locator('[data-testid="analyze-project-button"]');
    await analyzeBtn.click();

    // Wait for analysis to complete and Summary tab to show results
    await expect(page.getByText("Project Verdict")).toBeVisible({ timeout: 20000 });
    await expect(page.getByText("Mock Fixture Quarantine")).toBeVisible();
    await expect(page.getByText("Total Files")).toBeVisible();
    await expect(page.getByText("Total Lines")).toBeVisible();
    await expect(page.getByText("API Candidates")).toBeVisible();
    await expect(page.getByText("Resolved Imports")).toBeVisible();

    // Switch to Dependencies & Graph tab
    const graphTab = page.locator('[data-testid="project-tab-graph"]');
    await graphTab.click();

    // Verify cross-file import relationships are rendered
    await expect(page.getByText("Cross-File Relationships")).toBeVisible();
    await expect(page.getByText("main.py").first()).toBeVisible();
    await expect(page.getByText("services.payment").first()).toBeVisible();

    // Test clicking "View target file (services/payment.py)" from dependencies graph
    const viewTargetBtn = page.getByRole("button", { name: /View target file \(services\/payment\.py\)/i });
    await expect(viewTargetBtn).toBeVisible();
    await viewTargetBtn.click();
    await expect(page.getByText("Editing: services/payment.py")).toBeVisible();

    // Switch to Files tab
    const filesTab = page.locator('[data-testid="project-tab-files"]');
    await filesTab.click();
    await expect(page.getByText("services/payment.py").first()).toBeVisible();
    await expect(page.getByText("main.py").first()).toBeVisible();
  });

  test("4. Inspect verified issues and jump from issue to source file", async ({ page }) => {
    // Intercept project analysis request with a verified issue to test issue jump button
    await page.route("**/api/v1/analyze/project", async (route) => {
      const mockProjectReport = {
        project_name: "test_project",
        total_files: 2,
        total_lines: 20,
        parsed_files_count: 2,
        syntax_errors_count: 0,
        resolved_imports_count: 1,
        unresolved_imports_count: 0,
        circular_dependencies: [],
        ecosystem: "stripe",
        verdict: "issues_found",
        engine_version: "0.1.0",
        is_mock: false,
        evidence_trust: "live_official_source",
        summary: "Detected 1 verified API contract violation across project files.",
        files: [
          {
            path: "main.py",
            total_lines: 8,
            parse_status: "success",
            imports: [],
            calls_count: 1,
            candidates: [],
            defined_symbols: ["handle_checkout"],
          },
          {
            path: "services/payment.py",
            total_lines: 12,
            parse_status: "success",
            imports: [],
            calls_count: 1,
            candidates: [],
            defined_symbols: ["process_order"],
          },
        ],
        relationships: [
          {
            source_file: "main.py",
            imported_symbol: "process_order",
            target: "services.payment",
            target_file: "services/payment.py",
            status: "resolved",
            reason: "Matched project file 'services/payment.py'",
            is_circular: false,
          },
        ],
        verified_issues: [
          {
            issue_id: "iss_test_1",
            file_path: "services/payment.py",
            violation_type: "parameter_deprecated",
            source_location: { lineno: 5, col_offset: 4 },
            claim_checked: "source parameter deprecated",
            verified_quote: "You can no longer use the source parameter.",
            source_url: "https://docs.stripe.com/api/charges/create",
            supporting_evidence_id: "ev_test_1",
            explanation: "Parameter 'source' is deprecated in modern Stripe APIs.",
            confidence: 1.0,
          },
        ],
        total_candidates: 1,
        unresolved_candidates_count: 0,
        limitations_and_caveats: [],
        disclaimer: "Deterministic static AST verification.",
        ai_suggestions: [],
        evidence_items: [],
      };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockProjectReport),
      });
    });

    // Switch to Multi-File Project view
    await page.locator('[data-testid="nav-tab-project"]').click();
    await expect(page.getByText("Editing: main.py")).toBeVisible();

    // Run analysis
    await page.locator('[data-testid="analyze-project-button"]').click();
    await expect(page.getByText("Project Verdict")).toBeVisible({ timeout: 15000 });
    await expect(page.getByText("Contract Violations Found")).toBeVisible();

    // Open Issues tab
    const issuesTab = page.locator('[data-testid="project-tab-issues"]');
    await issuesTab.click();

    // Verify issue card is rendered with file_path and lineno
    const jumpBtn = page.locator('[data-testid="jump-to-line-button"]').first();
    await expect(jumpBtn).toBeVisible();
    await expect(jumpBtn).toContainText("services/payment.py:5");
    await expect(page.getByText(/parameter.*deprecated/i).first()).toBeVisible();

    // Click jump to line button
    await jumpBtn.click();

    // Active file should now be services/payment.py
    await expect(page.getByText("Editing: services/payment.py")).toBeVisible();
  });

  test("5. Switching back to Verification Studio preserves single-file workflow", async ({ page }) => {
    // Switch to Multi-File Project view
    await page.locator('[data-testid="nav-tab-project"]').click();
    await expect(page.getByText("Multi-File Project").first()).toBeVisible();

    // Switch back to Verification Studio
    await page.locator('[data-testid="nav-tab-editor"]').click();

    // Verify single-file studio elements are back
    await expect(page.getByText("payment_handler.py")).toBeVisible();
    await expect(page.locator('[data-testid="run-verify-button"]')).toBeVisible();

    // Verify presets in single-file mode
    await page.getByRole("button", { name: "PaymentIntent (Clean)" }).click();
    await expect(page.locator(".monaco-editor")).toContainText("PaymentIntent");
  });
});
