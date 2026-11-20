import type { NextConfig } from "next";

// The FastAPI backend. Proxied under /api so the browser sees one origin
// (no CORS, and navigator.sendBeacon works for saving progress on close).
const API_ORIGIN = process.env.CLOUDREADER_API_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  devIndicators: false,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` }];
  },
};

export default nextConfig;
