import { existsSync } from "node:fs";
import { defineConfig } from "@playwright/test";

const replitChromium = "/repl/tools/bin/chromium";
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_PATH
  || (existsSync(replitChromium) ? replitChromium : undefined);

const launchOptions = {
  args: ["--font-render-hinting=none"],
  ...(executablePath ? { executablePath } : {}),
};

export default defineConfig({
  testDir: "./tests/visual",
  outputDir: "./test-results",
  snapshotPathTemplate: "{testDir}/__screenshots__/{projectName}/{arg}{ext}",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 2 : 0,
  reporter: [
    ["line"],
    ["html", { outputFolder: "playwright-report", open: "never" }],
  ],
  expect: {
    timeout: 10_000,
    toHaveScreenshot: {
      animations: "disabled",
      caret: "hide",
      maxDiffPixelRatio: 0.001,
      scale: "css",
      threshold: 0.15,
    },
  },
  use: {
    baseURL: "http://127.0.0.1:4173",
    colorScheme: "dark",
    locale: "en-US",
    reducedMotion: "reduce",
    screenshot: "only-on-failure",
    timezoneId: "UTC",
    trace: "retain-on-failure",
    video: "off",
  },
  projects: [
    {
      name: "desktop",
      use: {
        viewport: { width: 1440, height: 1000 },
        deviceScaleFactor: 1,
        hasTouch: false,
        isMobile: false,
        launchOptions,
      },
    },
    {
      name: "mobile",
      use: {
        viewport: { width: 390, height: 844 },
        deviceScaleFactor: 1,
        hasTouch: true,
        isMobile: true,
        launchOptions,
      },
    },
  ],
  webServer: {
    command: [
      "cd ..",
      "visual_root=$(mktemp -d /tmp/ops-kpi-playwright-next-ui.XXXXXX)",
      "trap 'rm -rf \"$visual_root\"' EXIT INT TERM",
      "tar -C next-ui --exclude='./node_modules' --exclude='./.next' --exclude='./.visual-out' --exclude='./out' --exclude='./playwright-report' --exclude='./test-results' --exclude='./tests' -cf \"$visual_root/source.tar\" .",
      "tar -C \"$visual_root\" -xf \"$visual_root/source.tar\"",
      "rm \"$visual_root/source.tar\"",
      "ln -s \"$PWD/next-ui/node_modules\" \"$visual_root/node_modules\"",
      "PLAYWRIGHT_VISUAL_TEST=1 CLERK_PUBLISHABLE_KEY= VITE_CLERK_PUBLISHABLE_KEY= NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY= npm run build --prefix \"$visual_root\"",
      "UI_DIST_PATH=\"$visual_root/.visual-out\" PREVIEW_ADMIN_MODE=1 PREVIEW_LIVE_DATA=0 CLERK_PUBLISHABLE_KEY= VITE_CLERK_PUBLISHABLE_KEY= NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY= uvicorn po_api:app --host 127.0.0.1 --port 4173",
    ].join(" && "),
    url: "http://127.0.0.1:4173/api/preview-mode",
    gracefulShutdown: {
      signal: "SIGTERM",
      timeout: 5_000,
    },
    reuseExistingServer: false,
    timeout: 180_000,
  },
});