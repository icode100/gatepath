import type { NextConfig } from "next";

const isVercel = process.env.VERCEL === "1";

const nextConfig: NextConfig = {
  // The standalone server is for the Docker image. Vercel's native Next.js
  // service owns its build output and function tracing.
  output: isVercel ? undefined : "standalone",
  poweredByHeader: false,
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
