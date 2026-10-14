import { defineConfig } from "vitest/config";
import { cloudflareTest } from "@cloudflare/vitest-plugin";

export default defineConfig({
  plugins: [cloudflareTest({
    wrangler: { configPath: "./wrangler.jsonc" },
    miniflare: { bindings: {
      BOT_TOKEN: "test-token", ALLOWED_USER_ID: "42", CHAT_ID: "42", WEBHOOK_SECRET: "test-secret",
      PUBLIC_BASE_URL: "https://relay.example.com", RELEASE_TAG: "v0.1.0",
    } },
  })],
  test: { include: ["test/**/*.test.ts"], fileParallelism: false },
});
