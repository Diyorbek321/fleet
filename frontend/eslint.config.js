import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default tseslint.config(
  // Build and tooling artifacts, not source. `coverage/` in particular ships
  // vendored istanbul scripts that fail every rule here and buried the three
  // real errors this config was catching.
  { ignores: ["dist", "coverage", "node_modules"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      "@typescript-eslint/no-unused-vars": "off",
    },
  },
  {
    // Playwright specs and the perf probe are Node scripts, not React. The
    // hooks rule fires on Playwright's own `use` fixture callback — it sees a
    // bare `use(...)` inside a lowercase function and reports a misplaced React
    // Hook, which is a false positive this directory can never satisfy.
    files: ["e2e/**/*.{ts,tsx}", "scripts/**/*.{js,mjs,ts}"],
    languageOptions: { globals: globals.node },
    rules: {
      "react-hooks/rules-of-hooks": "off",
      "react-refresh/only-export-components": "off",
    },
  },
);
