import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Enable static export for bundling with Python package
  output: "export",

  // Disable image optimization (not supported in static export)
  images: {
    unoptimized: true,
  },

  // Trailing slashes for static hosting compatibility
  trailingSlash: true,
};

export default nextConfig;
