import { resolve } from "path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/** App 壳独立构建 → dist-app（8081），不影响默认 dist（8080） */
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8098",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist-app",
    emptyOutDir: true,
    rollupOptions: {
      input: resolve(__dirname, "app.html"),
    },
  },
});
