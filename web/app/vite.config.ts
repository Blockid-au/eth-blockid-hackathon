import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/",
  build: {
    outDir: "../dist",
    emptyOutDir: true,
    target: "es2020",
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("node_modules/react") || id.includes("node_modules/scheduler") || id.includes("react-router")) return "react";
        },
      },
    },
  },
  server: { host: true, proxy: { "/api": { target: "http://127.0.0.1:8080", rewrite: (p) => p.replace(/^\/api/, "") } } },
});
