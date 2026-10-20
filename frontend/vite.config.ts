import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // The dashboard calls /api/...; Vite forwards it to the FastAPI backend, so no CORS setup.
    proxy: {
      "/api": { target: "http://localhost:8000", rewrite: (path) => path.replace(/^\/api/, "") },
    },
  },
});
