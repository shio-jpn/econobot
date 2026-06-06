import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        dark: {
          bg: '#0a0a0a',
          text: '#f0f0f0',
          accent: '#ffffff',
          muted: '#666666',
          border: '#2a2a2a',
          card: '#141414',
          hover: '#1e1e1e',
        },
        light: {
          bg: '#ffffff',
          text: '#0a0a0a',
          accent: '#000000',
          muted: '#888888',
          border: '#e5e5e5',
          card: '#f5f5f5',
          hover: '#eeeeee',
        },
        sage: {
          bg: '#1a2418',
          text: '#d4e8cf',
          accent: '#7fc27a',
          muted: '#5a7a55',
          border: '#2d3d2b',
          card: '#1f2d1c',
          hover: '#243022',
        },
      },
      fontFamily: {
        sans: [
          '-apple-system',
          'BlinkMacSystemFont',
          'Segoe UI',
          'Helvetica Neue',
          'Arial',
          'sans-serif',
        ],
      },
      borderRadius: {
        sm: '4px',
        DEFAULT: '4px',
        md: '6px',
        lg: '8px',
      },
      animation: {
        'fade-in': 'fadeIn 0.15s ease-out',
        'slide-up': 'slideUp 0.2s ease-out',
        'pulse-once': 'pulseOnce 0.3s ease-out',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { transform: 'translateY(8px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        pulseOnce: {
          '0%': { transform: 'scale(1)' },
          '50%': { transform: 'scale(1.05)' },
          '100%': { transform: 'scale(1)' },
        },
      },
      maxWidth: {
        app: '480px',
      },
    },
  },
  plugins: [],
};

export default config;
