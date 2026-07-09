import { resolve } from "path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  root: resolve(__dirname, "fixtures/plan-poi"),
  server: { port: 5199, strictPort: true },
});
