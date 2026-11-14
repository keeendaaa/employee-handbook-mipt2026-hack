import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath, URL } from "node:url";
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    proxy: {
      "/api": {
        target: process.env.NAVIGATOR_API_URL || "http://127.0.0.1:8000",
        changeOrigin: false,
      },
      "/health": {
        target: process.env.NAVIGATOR_API_URL || "http://127.0.0.1:8000",
      },
    },
  },
  build: {
    outDir: "dist",
    assetsDir: "ui-assets",
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("/@ui-sdk/")) return "ui-sdk";
          if (id.includes("/motion") || id.includes("/framer-motion"))
            return "motion";
          if (
            id.includes("/@radix-ui/") ||
            id.includes("/cmdk") ||
            id.includes("/@hugeicons/")
          )
            return "controls";
          if (id.includes("/react-dom") || id.includes("/react/"))
            return "react";
        },
      },
    },
  },
});
