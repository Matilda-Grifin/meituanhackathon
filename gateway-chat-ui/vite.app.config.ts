import { resolve } from "path";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

/** App 壳独立构建 → dist-app（8081），不影响默认 dist（8080） */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  return {
    plugins: [react()],
    // mode=app → .env.app；远端构建常缺 .env.app，这里给出 App 壳默认值，避免露出开发用 Gateway 面板
    define: {
      "import.meta.env.VITE_APP_SHELL": JSON.stringify(env.VITE_APP_SHELL || "mobile"),
      "import.meta.env.VITE_COMPACT_UI": JSON.stringify(env.VITE_COMPACT_UI || "true"),
      "import.meta.env.VITE_AUTO_CONNECT": JSON.stringify(env.VITE_AUTO_CONNECT || "true"),
      "import.meta.env.VITE_SHOW_DEBUG": JSON.stringify(env.VITE_SHOW_DEBUG || "false"),
    },
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
  };
});
