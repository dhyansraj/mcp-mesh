import { defineConfig, globalIgnores } from "eslint/config";

const eslintConfig = defineConfig([
  globalIgnores(["dist/**", "node_modules/**"]),
  {
    files: ["**/*.js", "**/*.jsx"],
    rules: {
      "no-unused-vars": "warn",
      "no-undef": "error",
    },
  },
  {
    files: ["**/*.ts", "**/*.tsx"],
    rules: {
      "no-unused-vars": "off",
    },
  },
]);

export default eslintConfig;
