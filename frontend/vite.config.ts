import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const workspaceRoot = path.resolve(fileURLToPath(new URL("..", import.meta.url)));

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      components: path.resolve(workspaceRoot, "frontend/src/components")
    }
  },
  server: {
    fs: {
      allow: [workspaceRoot]
    },
    port: 5151,
    proxy: {
      "/api": {
        target: process.env.VITE_API_PROXY ?? "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, "")
      }
    }
  }
});
