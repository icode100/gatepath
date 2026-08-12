import type { NextConfig } from "next";

const isVercel = process.env.VERCEL === "1";

const nextConfig: NextConfig = {
  // The standalone server is for the Docker image. Vercel's native Next.js
  // service owns its build output and function tracing.
  output: isVercel ? undefined : "standalone",
  poweredByHeader: false,
  async headers() {
    return [
      {
        source: "/sw.js",
        headers: [
          { key: "Content-Type", value: "application/javascript; charset=utf-8" },
          { key: "Cache-Control", value: "no-cache, no-store, must-revalidate" },
          { key: "Content-Security-Policy", value: "default-src 'self'; script-src 'self'; object-src 'none'" },
          { key: "Service-Worker-Allowed", value: "/" },
        ],
      },
      {
        source: "/offline.html",
        headers: [
          { key: "Cache-Control", value: "public, max-age=0, must-revalidate" },
          {
            key: "Content-Security-Policy",
            value: "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
          },
        ],
      },
    ];
  },
  async rewrites() {
    // Vercel Services routes these paths before the request reaches Next.js.
    // Keep the proxy here for `npm run dev` and the Docker Compose frontend.
    if (isVercel) {
      return [];
    }

    const backend = process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000";
    return [
      {
        source: "/api/v1/:path*",
        destination: `${backend}/api/v1/:path*`,
      },
      {
        source: "/health",
        destination: `${backend}/health`,
      },
      {
        source: "/health/backend",
        destination: `${backend}/health`,
      },
    ];
  },
};

export default nextConfig;
