/** @type {import('tailwindcss').Config} */

// Warm charcoal neutrals and a single grass-green accent. Remapping the palettes the
// templates already use (zinc, emerald, teal) restyles every page consistently.
const neutral = {
  50: '#f7f6f3', 100: '#eeede9', 200: '#dcdad4', 300: '#c2bfb7', 400: '#a29e95',
  500: '#837f77', 600: '#66635d', 700: '#4a4844', 800: '#33322f', 900: '#252422', 950: '#1a1918',
};
const grass = {
  50: '#f2f8eb', 100: '#e0f0cf', 200: '#c3e2a3', 300: '#a3d077', 400: '#88bd56', 500: '#6ea33d',
  600: '#56832e', 700: '#436526', 800: '#365022', 900: '#2d431f', 950: '#16250c',
};

module.exports = {
  // Classes are also built from strings inside the page scripts, so scan both.
  content: ['../templates/**/*.html', '../static/js/**/*.js'],
  theme: {
    extend: {
      colors: { zinc: neutral, emerald: grass, teal: grass },
      fontFamily: {
        sans: ['"Segoe UI Variable Text"', '"Segoe UI"', 'system-ui', '-apple-system', 'Roboto', 'Ubuntu', 'sans-serif'],
        display: ['"Segoe UI Variable Display"', '"Segoe UI"', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['"Cascadia Mono"', 'Consolas', 'ui-monospace', 'monospace'],
      },
    },
  },
};
