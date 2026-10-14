import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  transpilePackages: ["@aiciv/world-engine", "@aiciv/event-contracts", "@aiciv/shared-types"],
  // Static export works too (output: "export") for hosting the shell on any CDN; the API is separate.
  output: process.env.AICIV_STATIC_EXPORT === "1" ? "export" : undefined,
  images: { unoptimized: true },
};

export default config;
