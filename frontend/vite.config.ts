import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite config; polling is required so Docker on Windows picks up source edits.
export default defineConfig({
  plugins: [react()],
  envPrefix: ["VITE_", "REACT_APP_"],
  server: {
    host: "0.0.0.0",
    port: 5173,
    watch: {
      usePolling: true,
    },
  },
});
