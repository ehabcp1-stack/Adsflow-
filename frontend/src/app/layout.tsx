import type { Metadata, Viewport } from 'next';

import { AppShell } from '@/components/AppShell';
import { LocaleProvider } from '@/i18n/LocaleProvider';

import './globals.css';

export const metadata: Metadata = {
  title: 'AdFlow AI · by TADAFQ',
  description: 'Premium AI advertising production studio — Iraqi Arabic first.',
  icons: { icon: '/favicon.svg' },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  themeColor: '#F6F7F9',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // Arabic (RTL) is the default; LocaleProvider swaps dir/lang on the client.
    <html lang="ar" dir="rtl">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        {/* Fonts degrade to the local stack when offline. */}
        <link
          href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;500;600;700&family=Inter:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <LocaleProvider>
          <AppShell>{children}</AppShell>
        </LocaleProvider>
      </body>
    </html>
  );
}
