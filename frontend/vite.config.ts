/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";
import { componentTagger } from "lovable-tagger";

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => ({
  server: {
    host: "::",
    port: 8080,
  },
  plugins: [react(), mode === "development" && componentTagger()].filter(Boolean),
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      // Pages and feature components count too: the screens that report money
      // are where a presentation bug does the damage, and leaving them out of
      // coverage made the suite look healthier than it was.
      include: [
        "src/lib/**",
        "src/hooks/**",
        "src/contexts/**",
        "src/pages/**",
        "src/components/trips/**",
        "src/components/dashboard/**",
        "src/components/maintenance/**",
      ],
      // src/components/ui/** is vendored shadcn primitives — not our code to test.
      exclude: ["**/*.test.*", "**/node_modules/**", "src/test/**"],
    },
  },
}));
