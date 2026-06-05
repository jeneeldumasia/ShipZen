/** @type {import('next').NextConfig} */
const nextConfig = {
  // Allow the API server to be configured per-environment
  // Default points to the local docker-compose stack
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
  },
};

export default nextConfig;
