import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "path";

export default defineConfig({
  plugins: [react()],
  base: "/",
  build: {
    outDir: resolve(__dirname, "../replay_tool/static"),
    emptyOutDir: true,
    assetsDir: "assets",
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/icons": "http://127.0.0.1:8000",
    },
  },
});
