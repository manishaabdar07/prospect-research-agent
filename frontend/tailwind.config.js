/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#f2f6fc",
          100: "#e3ecf9",
          200: "#c2d6f0",
          300: "#8fb3e2",
          400: "#5689cf",
          500: "#3468b5",
          600: "#265196",
          700: "#20417a",
          800: "#1e3866",
          900: "#1c3157",
        },
      },
    },
  },
  plugins: [],
};
