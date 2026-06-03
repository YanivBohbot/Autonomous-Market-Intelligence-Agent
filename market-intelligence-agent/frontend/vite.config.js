var _a;
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
var API_TARGET = (_a = process.env.VITE_API_TARGET) !== null && _a !== void 0 ? _a : "http://127.0.0.1:8000";
export default defineConfig({
    plugins: [react()],
    server: {
        port: 5173,
        proxy: {
            "/stream": { target: API_TARGET, changeOrigin: true },
            "/approve": { target: API_TARGET, changeOrigin: true },
            "/health": { target: API_TARGET, changeOrigin: true },
            "/livekit": { target: API_TARGET, changeOrigin: true },
        },
    },
});
