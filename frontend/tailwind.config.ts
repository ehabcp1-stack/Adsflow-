import type { Config } from 'tailwindcss';

/**
 * AdFlow AI — Premium Creative Studio design tokens.
 * Light application surface + optional dark graphite workspace.
 */
const config: Config = {
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        canvas: '#F6F7F9',
        surface: '#FFFFFF',
        raised: '#FCFCFD',
        ink: { DEFAULT: '#101828', soft: '#344054', muted: '#667085', faint: '#98A2B3' },
        line: { DEFAULT: '#E7EAEE', strong: '#D5DAE1' },
        accent: { DEFAULT: '#2563EB', dark: '#1D4ED8', soft: '#EFF4FF', ring: '#B7CCFF' },
        gold: '#C9A227',
        graphite: { 950: '#0C0E12', 900: '#121419', 800: '#181B22', 700: '#22262F', 600: '#2E333D', line: '#2A2F39' },
        ok: '#0E9F6E',
        warn: '#D97706',
        danger: '#DC2626',
      },
      fontFamily: {
        sans: ['var(--font-latin)', 'Inter', 'system-ui', 'sans-serif'],
        arabic: ['var(--font-arabic)', 'Cairo', 'Tahoma', 'sans-serif'],
      },
      borderRadius: { xl: '14px', '2xl': '18px', '3xl': '24px' },
      boxShadow: {
        card: '0 1px 2px rgba(16,24,40,0.04), 0 1px 3px rgba(16,24,40,0.06)',
        lift: '0 8px 24px -6px rgba(16,24,40,0.10), 0 2px 6px rgba(16,24,40,0.05)',
        focus: '0 0 0 4px rgba(37,99,235,0.14)',
      },
      keyframes: {
        'fade-up': { '0%': { opacity: '0', transform: 'translateY(6px)' }, '100%': { opacity: '1', transform: 'none' } },
        shimmer: { '100%': { transform: 'translateX(100%)' } },
        'pulse-soft': { '0%,100%': { opacity: '1' }, '50%': { opacity: '0.55' } },
      },
      animation: {
        'fade-up': 'fade-up .28s cubic-bezier(.2,.7,.3,1) both',
        shimmer: 'shimmer 1.6s infinite',
        'pulse-soft': 'pulse-soft 1.8s ease-in-out infinite',
      },
    },
  },
  plugins: [],
};
export default config;
