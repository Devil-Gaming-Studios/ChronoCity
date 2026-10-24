import { defineConfig, mergeConfig } from "vite";
import base from "./vite.config";

export default mergeConfig(base, defineConfig({
  server: { port: 5174, strictPort: true, proxy: {
    "/api": { target: "http://127.0.0.1:8002", changeOrigin: true },
    "/ws": { target: "ws://127.0.0.1:8002", ws: true },
  } },
}));
