import { defineConfig, globalIgnores } from "eslint/config";
import js from "@eslint/js";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";

const eslintConfig = defineConfig([
  // "**/dist/**", not "dist/**": the latter is root-relative and missed
  // src/ui/demo/dist/, so `npx eslint demo` reported 6 errors and 9 warnings
  // from inside the demo's own minified build artifact.
  globalIgnores(["**/dist/**", "node_modules/**", "*.config.*", "*.tsbuildinfo"]),
  {
    files: ["**/*.js", "**/*.jsx", "**/*.mjs"],
    ...js.configs.recommended,
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
    },
    rules: {
      "no-unused-vars": "warn",
      "no-undef": "error",
    },
  },
  ...tseslint.configs.recommended.map((config) => ({
    ...config,
    files: ["**/*.ts", "**/*.tsx"],
  })),
  {
    files: ["**/*.ts", "**/*.tsx", "**/*.jsx"],
    plugins: { "react-hooks": reactHooks },
    languageOptions: {
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
      globals: { ...globals.browser, ...globals.node },
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "@typescript-eslint/no-unused-vars": [
        "warn",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      "@typescript-eslint/no-explicit-any": "warn",
    },
  },
]);

export default eslintConfig;
