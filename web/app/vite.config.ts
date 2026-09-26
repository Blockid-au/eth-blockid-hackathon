import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

/** emptyOutDir wipes ../dist: keep runtime JSON dropped at the dist root (e.g. hsk-demo.json) across rebuilds,
 *  and copy ../hsk-demo.json (web/ root, like hoodi-demo.json) into dist when present. */
function keepDistJson() {
  const dist = resolve(__dirname, "../dist");
  const kept = new Map<string, Buffer>();
  return {
    name: "keep-dist-json",
    buildStart() {
      if (!existsSync(dist)) return;
      for (const f of readdirSync(dist)) if (f.endsWith(".json")) kept.set(f, readFileSync(resolve(dist, f)));
    },
    closeBundle() {
      for (const [f, b] of kept) writeFileSync(resolve(dist, f), b);
      const src = resolve(__dirname, "../hsk-demo.json");
      if (existsSync(src)) writeFileSync(resolve(dist, "hsk-demo.json"), readFileSync(src));
    },
  };
}

export default defineConfig({
  plugins: [react(), keepDistJson()],
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
