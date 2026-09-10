/**
 * Two build shapes:
 *   default            — talks to the FastAPI backend (local / self-hosted).
 *   NEXT_PUBLIC_DEMO_MODE=true — fully static showcase for Netlify: every API
 *                        call is answered from public/demo/snapshot.json.
 */
const demoMode = process.env.NEXT_PUBLIC_DEMO_MODE === 'true';

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  ...(demoMode ? { output: 'export', trailingSlash: true } : {}),
  images: {
    unoptimized: demoMode,
    remotePatterns: [
      { protocol: 'http', hostname: 'localhost' },
      { protocol: 'https', hostname: '**' },
    ],
  },
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000',
    NEXT_PUBLIC_DEMO_MODE: demoMode ? 'true' : 'false',
  },
};

export default nextConfig;
