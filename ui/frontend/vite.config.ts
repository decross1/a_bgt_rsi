/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// server.host:true binds 0.0.0.0 so the dev server is reachable both
// through an SSH tunnel and directly over the LAN. See ui/frontend/README.md.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { host: true, port: 5173 },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.{test,spec}.{ts,tsx}", "tests/**/test_*.{ts,tsx}"],
  },
});
