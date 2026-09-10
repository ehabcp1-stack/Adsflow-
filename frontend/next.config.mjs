/**
 * Standard Next.js App Router build — Server Components and the normal
 * Next.js runtime are preserved. On Netlify the framework adapter handles it;
 * nothing here overrides framework detection.
 *
 * Runtime behaviour (mock / development / production) is decided by
 * src/lib/config.ts from NEXT_PUBLIC_* variables, never baked in here — so no
 * host or port is ever compiled into a production bundle.
 *
 * NEXT_STATIC_EXPORT=true is an opt-in fallback that produces `out/` for
 * drag-and-drop hosting. It is not the primary deployment path.
 */
const staticExport = process.env.NEXT_STATIC_EXPORT === 'true';

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  ...(staticExport ? { output: 'export', trailingSlash: true } : {}),
  images: {
    unoptimized: staticExport,
    remotePatterns: [
      { protocol: 'https', hostname: '**' },
      { protocol: 'http', hostname: 'localhost' },
    ],
  },
};

export default nextConfig;
