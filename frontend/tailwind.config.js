/** Ingaze look: navy ink, indigo brand, slate surfaces, Funnel Display + Work Sans. */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#1e1b4b",
        brand: { DEFAULT: "#4f46e5", dark: "#4338ca", soft: "#eef2ff" },
        accent: "#fff047",
      },
      fontFamily: {
        display: ['"Funnel Display"', "sans-serif"],
        sans: ['"Work Sans"', "sans-serif"],
      },
      borderRadius: { btn: "10px" },
    },
  },
  plugins: [],
};
