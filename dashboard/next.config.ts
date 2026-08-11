import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  outputFileTracingRoot: import.meta.dirname,
  async rewrites() {
    const backend = process.env.FLARE_API_URL ?? "http://localhost:8000";
    return [
      {
        source: "/api/:path((?!.*/stream$).*)",
        destination: `${backend}/api/:path`,
      },
      { source: "/readyz", destination: `${backend}/readyz` },
    ];
  },
};

export default nextConfig;
