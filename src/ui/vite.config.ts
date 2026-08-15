/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

import { shipFontLicence } from "./vite.fonts";
import { pinProductionBuild } from "./vite.env";

export default defineConfig(({ command }) => {
  // Read vite.env.ts before touching this line. dist/ is what //go:embed
  // compiles into the meshui binary, and without the pin an inherited NODE_ENV
  // puts React's 1,087,205 B development bundle there in place of the 722,653 B
  // production one, with byte-identical CSS and no other signal anywhere.
  pinProductionBuild(command);

  return {
    base: "./",
    plugins: [react(), tailwindcss(), shipFontLicence()],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "."),
      },
    },
    build: {
      outDir: "dist",
    },
    server: {
      proxy: {
        "/api": {
          target: "http://localhost:8000",
          changeOrigin: true,
        },
      },
    },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./vitest.setup.ts"],
    },
  };
});
