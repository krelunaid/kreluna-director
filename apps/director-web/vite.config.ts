import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/health": "http://127.0.0.1:8080",
      "/ready": "http://127.0.0.1:8080",
      "/update": "http://127.0.0.1:8080",
      "/auth": "http://127.0.0.1:8080",
      "/me": "http://127.0.0.1:8080",
      "/chat": "http://127.0.0.1:8080",
      "/tasks": "http://127.0.0.1:8080",
      "/agents": "http://127.0.0.1:8080",
      "/devices": "http://127.0.0.1:8080",
      "/approvals": "http://127.0.0.1:8080",
      "/evidence": "http://127.0.0.1:8080",
      "/library": "http://127.0.0.1:8080",
      "/audit": "http://127.0.0.1:8080",
      "/overview": "http://127.0.0.1:8080",
      "/ai": "http://127.0.0.1:8080",
      "/kill-switch": "http://127.0.0.1:8080",
      "/policy": "http://127.0.0.1:8080",
      "/ws": {
        target: "ws://127.0.0.1:8080",
        ws: true,
      },
    },
  },
});
