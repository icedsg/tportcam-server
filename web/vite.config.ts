import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built into the Python package (camgrid_hub/web/); `npm run dev` proxies the API to a hub on 8780.
const hub = process.env.HUB_URL || "http://127.0.0.1:8780";

export default defineConfig({
  plugins: [react()],
  base: "/",
  build: { outDir: "../camgrid_hub/web", emptyOutDir: true },
  server: { proxy: { "/api": hub, "/go2rtc": hub } },
});
