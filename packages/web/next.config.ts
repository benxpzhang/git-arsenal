import type { NextConfig } from "next";

const BACKEND = process.env.ARSENAL_API_URL || "http://localhost:8003";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      { source: "/api/auth/:path*", destination: `${BACKEND}/api/auth/:path*` },
      { source: "/api/search",      destination: `${BACKEND}/api/search` },
      { source: "/api/repo/:path*", destination: `${BACKEND}/api/repo/:path*` },
      { source: "/api/galaxy/:path*", destination: `${BACKEND}/api/galaxy/:path*` },
      { source: "/api/conversations/:path*", destination: `${BACKEND}/api/conversations/:path*` },
      { source: "/api/conversations", destination: `${BACKEND}/api/conversations` },
      { source: "/api/health",       destination: `${BACKEND}/api/health` },
    ];
  },
};

export default nextConfig;
