import { defineConfig } from "@playwright/test"

const FRONTEND = process.env.E2E_BASE_URL || "http://127.0.0.1:5173"
const API = process.env.E2E_API_URL || "http://127.0.0.1:8000"

export default defineConfig({
  testDir: "./tests",
  timeout: 60_000,
  fullyParallel: false,
  retries: 0,
  use: {
    baseURL: FRONTEND,
    trace: "on-first-retry",
  },
  metadata: { api: API },
})
