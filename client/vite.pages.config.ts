import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { version } from "./package.json";

export default defineConfig({
  root: "src/renderer",
  plugins: [react()],
  define: { "import.meta.env.VITE_YUDAO_RELEASE": JSON.stringify(version) },
  build: { outDir: "../../out/renderer", emptyOutDir: true },
});
