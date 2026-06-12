/** @type {import('tailwindcss').Config} */
// Tokens remapped from cruisenow.ai (extracted via designlang) onto the Solace
// green/white/black brand. Spacing, radii and easing match the reference 1:1.
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Solace brand — green axis replaces Cruise's blue (#2251f9 -> #0B6B53)
        solace: {
          green: {
            DEFAULT: '#0B6B53',
            50: '#E7F4EF',
            100: '#CDE9DF',
            300: '#7CCBB2',
            500: '#1FBF8F', // mint accent (was Cruise accent #518bff)
            600: '#0F8A68',
            700: '#0B6B53',
            900: '#063B2E',
          },
          mint: '#1FBF8F',
          soft: '#E7F4EF',
        },
        ink: '#0A0F0D', // near-black (was Cruise #1e1e2e)
        offwhite: '#F6FAF8', // section bg (was Cruise #f4f5f7)
        muted: '#5B6B64', // secondary text (was Cruise #4d4f5c)
        slate: '#3C5560', // the real Solace logo color, kept as an optional accent
        // app.forhims.com neutrals, extracted 1:1 — the Product page runs on these
        paper: '#f0f0f0',
        himspurple: '#5d48db', // reference accent; swap for solace green where remapped
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        display: ['"Instrument Serif"', 'Georgia', 'serif'], // free lookalike for Cruise's Cirka
        // Figtree's round, friendly geometry is the closest free match to
        // hims&hers' Sofia Pro at display sizes (Sofia Sans, kept as fallback,
        // runs too narrow/grotesque despite the name).
        sofia: ['Figtree', '"Sofia Sans"', 'Inter', 'system-ui', 'sans-serif'],
      },
      // Cruise spacing scale (2px base) — exact values extracted from the site
      spacing: {
        27: '27px',
        46: '46px',
        87: '87px',
        120: '120px',
        140: '140px',
      },
      borderRadius: {
        // Cruise radii scale: 4 · 8 · 16 · 24 · 40 · 100 · 200
        pill: '100px',
        blob: '200px',
        // forhims radii scale: 20 · 27 · 45 · 52 · 100
        tile: '20px',
        hims: '45px',
        'hims-lg': '52px',
      },
      boxShadow: {
        // Cruise's single soft elevation
        card: 'rgba(16, 24, 40, 0.05) 0px 1px 2px 0px',
        lift: '0 20px 50px -20px rgba(11, 107, 83, 0.25)',
        glow: '0 0 80px 0 rgba(31, 191, 143, 0.35)',
        // forhims elevations, extracted 1:1
        soft: 'rgba(0, 0, 0, 0.06) 0px 8px 30px 0px',
        pop: 'rgba(0, 0, 0, 0.25) 0px 9px 46px 0px',
        phone: 'rgba(0, 0, 0, 0.12) 0px 27px 104px 0px',
        halo: 'rgba(0, 0, 0, 0.11) 0px 8px 127px 0px',
      },
      letterSpacing: {
        // Cruise headings run very tight (~ -2.6px on 72px)
        tightest: '-0.04em',
        // forhims mega type runs even tighter (-14.3px on 248.9px)
        hims: '-0.0575em',
      },
      transitionTimingFunction: {
        // easeOutQuart — the single curve Cruise uses everywhere
        standard: 'cubic-bezier(0.25, 1, 0.5, 1)',
        // forhims' two curves: opacity 0.2s ease-out, transform 0.6s expo-out
        'hims-out': 'cubic-bezier(0.215, 0.61, 0.355, 1)',
        'hims-expo': 'cubic-bezier(0.19, 1, 0.22, 1)',
      },
      keyframes: {
        blink: { '0%,100%': { opacity: '0' }, '50%': { opacity: '1' } },
        drift: {
          '0%,100%': { transform: 'translate(0,0) scale(1)' },
          '50%': { transform: 'translate(20px,-30px) scale(1.05)' },
        },
        float: {
          '0%,100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-12px)' },
        },
      },
      animation: {
        blink: 'blink 1s steps(1) infinite',
        drift: 'drift 14s ease-in-out infinite',
        float: 'float 6s ease-in-out infinite',
      },
    },
  },
  plugins: [],
};
