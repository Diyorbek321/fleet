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
  build: {
    rollupOptions: {
      output: {
        /**
         * Split the dependencies that never change away from the app code that
         * changes every release.
         *
         * Everything shared used to land in one ~173 KB (gzipped) entry chunk
         * whose filename is content-hashed, so every deploy — including a
         * one-line copy fix — made every user re-download React, the router,
         * React Query and the whole UI kit over a link that delivers about
         * 46 KB/s. Splitting them out means a release invalidates only the app
         * chunk; the rest stays in the browser cache across deploys.
         *
         * Grouped by how often each moves, not by package: a chunk per
         * dependency would trade the download for dozens of extra requests.
         */
        manualChunks: {
          // Upgraded a few times a year at most.
          'vendor-react': ['react', 'react-dom', 'react-router-dom'],
          // Data layer.
          'vendor-query': ['@tanstack/react-query'],
          // Translations: three locale files plus i18next, none of which the
          // rest of the app has any reason to invalidate.
          'vendor-i18n': ['i18next', 'react-i18next', 'i18next-browser-languagedetector'],
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    // Unit tests only. The e2e/ specs import @playwright/test, which vitest
    // cannot collect — without this they fail the run while every actual
    // assertion passes, which reads as a broken suite.
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    exclude: ["e2e/**", "node_modules/**", "dist/**"],
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
