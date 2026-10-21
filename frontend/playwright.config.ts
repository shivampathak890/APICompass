import { defineConfig, devices } from "@playwright/test";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const pythonExe =
  process.platform === "win32"
    ? path.resolve(__dirname, "../.venv/Scripts/python.exe")
    : path.resolve(__dirname, "../.venv/bin/python");
const backendDir = path.resolve(__dirname, "../backend");

export default defineConfig({
  testDir: "./e2e",
  timeout: 45000,
  expect: {
    timeout: 12000,
  },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command: `"${pythonExe}" -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000`,
      cwd: backendDir,
      url: "http://127.0.0.1:8000/api/v1/health",
      reuseExistingServer: false,
      timeout: 60000,
      env: {
        APICOMPASS_DB_PATH: "data/test_e2e.db",
        MOCK_MODE: "True",
        LLM_PROVIDER: "disabled",
        SOURCE_RETENTION_ENABLED: "False",
        PYTHONPATH: ".",
      },
    },
    {
      command: "npm run preview -- --port 5173 --host 127.0.0.1",
      cwd: __dirname,
      url: "http://127.0.0.1:5173",
      reuseExistingServer: false,
      timeout: 60000,
    },
  ],
});
