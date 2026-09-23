import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    const target = process.env.API_PROXY_ORIGIN;
    if (!target || process.env.NEXT_PUBLIC_STATIC_DEMO === "true") return [];
    if (process.env.NEXT_PUBLIC_API_URL !== "") {
      throw new Error("NEXT_PUBLIC_API_URL must be empty when API_PROXY_ORIGIN is configured");
    }
    let upstream: URL;
    try {
      upstream = new URL(target);
      if (!["http:", "https:"].includes(upstream.protocol) ||
          upstream.username || upstream.password || upstream.pathname !== "/" ||
          upstream.search || upstream.hash) throw new Error("Invalid origin");
    } catch {
      throw new Error(
        "API_PROXY_ORIGIN must be a credential-free HTTP(S) origin without a path, query or fragment",
      );
    }
    return [{
      source: "/api/v1/:path*",
      destination: `${upstream.origin}/api/v1/:path*`,
    }];
  },
};

export default nextConfig;
