// Light theme, same system as the pitch deck: Geist / Geist Mono / Instrument Serif, warm white page, gold accent.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Geist", "ui-sans-serif", "system-ui", "-apple-system", "'Segoe UI'", "sans-serif"],
        mono: ["'Geist Mono'", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
        serif: ["'Instrument Serif'", "ui-serif", "Georgia", "serif"],
      },
      colors: {
        // Token names kept from the dark theme so class names still read the same; values are light.
        ink: { bg: "#F7F6F3", panel: "#FFFFFF", raised: "#F1EFEA", line: "#E4E2DC", text: "#0A0B0D", muted: "#5F636B", faint: "#8E9197" },
        gold: { DEFAULT: "#F0C06A", soft: "rgba(240,192,106,.16)", text: "#8A5D0B" },
        // st-* = status TEXT on white (dark enough for contrast); fill-* = status dots, lines and swatches.
        st: { calling: "#A86A06", yes: "#1E8A4C", no: "#C2412F", none: "#6B6F77" },
        fill: { calling: "#F2B35B", yes: "#5BD18B", no: "#EE7B6B", none: "#A3A6AD", released: "#C9CBD0" },
        live: { DEFAULT: "#2F6FD6", soft: "rgba(143,184,255,.14)" },
        sim: "#6B55C9",
      },
      boxShadow: { xs: "0 1px 2px rgba(10,11,13,.06)" },
    },
  },
  plugins: [],
};
