import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Enable static export for bundling with Python package
  output: "export",

  // Base path for path-based ingress routing (e.g. /ops/dashboard)
  basePath: process.env.NEXT_PUBLIC_UI_BASE_PATH || "",

  // Disable image optimization (not supported in static export)
  images: {
    unoptimized: true,
  },

  // Trailing slashes for static hosting compatibility
  trailingSlash: true,
};

export default nextConfig;
