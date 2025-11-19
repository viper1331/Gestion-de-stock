import path from "node:path";

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const workspaceRoot = path.resolve(new URL("..", import.meta.url).pathname);

export default defineConfig({
  plugins: [react()],
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
