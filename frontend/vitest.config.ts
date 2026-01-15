import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

const workspaceRoot = path.resolve(fileURLToPath(new URL("..", import.meta.url)));

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      components: path.resolve(workspaceRoot, "frontend/src/components")
    }
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./vitest.setup.ts"
  }
});
