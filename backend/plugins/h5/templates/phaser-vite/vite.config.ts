import { defineConfig } from "vite";

export default defineConfig({
  base: "./",
  server: {
    strictPort: false,
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
