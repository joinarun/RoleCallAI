import { defineConfig, devices, type WebServerConfig } from "@playwright/test";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const workspace = resolve(here, "../..");
const agent = resolve(workspace, "services/rolecall-agent");
const live = process.env.ROLECALL_E2E_LIVEKIT === "1";
const baseURL = "http://127.0.0.1:5173";
const apiURL = "http://127.0.0.1:8000";

const webServer: WebServerConfig[] = [];
if (live) {
  webServer.push({
    command: "docker compose up redis livekit",
    cwd: workspace,
    url: "http://127.0.0.1:7880",
    reuseExistingServer: true,
    timeout: 120_000,
  });
}
webServer.push(
  {
    command: "uv run uvicorn app.fast_api_app:app --host 127.0.0.1 --port 8000",
    cwd: agent,
    url: `${apiURL}/healthz`,
    reuseExistingServer: true,
    timeout: 120_000,
    env: {
      ...process.env,
      ROLECALL_ENV: live ? "local" : "test",
      ROLECALL_REPOSITORY: "memory",
      ROLECALL_PUBLIC_BASE_URL: baseURL,
      ROLECALL_COOKIE_SECURE: "false",
      ROLECALL_COOKIE_SIGNING_KEY: "playwright-local-signing-key-at-least-32-bytes",
      ROLECALL_LIVEKIT_URL: "ws://127.0.0.1:7880",
      ROLECALL_LIVEKIT_API_KEY:
        process.env.LIVEKIT_API_KEY ?? "replace-with-local-livekit-api-key",
      ROLECALL_LIVEKIT_API_SECRET:
        process.env.LIVEKIT_API_SECRET ?? "replace-with-local-livekit-secret-at-least-32-bytes",
      ROLECALL_ROOM_CREATE_RATE_PER_HOUR: "1000",
      ROLECALL_CAPABILITY_FAILURE_RATE_PER_MINUTE: "1000",
      OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT: "NO_CONTENT",
      ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS: "false",
    },
  },
  {
    command: `VITE_API_BASE_URL=${apiURL} npm run dev -- --host 127.0.0.1`,
    cwd: here,
    url: baseURL,
    reuseExistingServer: true,
    timeout: 120_000,
  },
);

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  timeout: 45_000,
  expect: { timeout: 8_000 },
  reporter: [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
  outputDir: "test-results",
  webServer,
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    permissions: ["microphone"],
    launchOptions: {
      args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"],
    },
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile-chromium", use: { ...devices["Pixel 7"] }, testIgnore: /live-meeting\.spec\.ts/ },
  ],
});
