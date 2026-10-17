import type { NextConfig } from "next";

// The production image (BUILD_STANDALONE) must never carry the pasted-token sign-in.
if (
  process.env.BUILD_STANDALONE === "true" &&
  process.env.NEXT_PUBLIC_ENABLE_DEV_TOKEN === "true"
) {
  throw new Error("NEXT_PUBLIC_ENABLE_DEV_TOKEN=true is not allowed in a standalone/image build.");
}

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // `standalone` produces a minimal self-contained server bundle for the
  // production Docker image. It is gated behind an env var because its trace
  // step creates symlinks, which Windows blocks without elevated privileges —
  // the Docker build (Linux) sets BUILD_STANDALONE=true, local Windows builds
  // skip it and still succeed.
  output: process.env.BUILD_STANDALONE === "true" ? "standalone" : undefined,
  experimental: {
    typedRoutes: true,
  },
};

export default nextConfig;
