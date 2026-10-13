import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

// Every entry is an explicit map so later tasks (#17, #18) can add their own
// entry without editing a single hard-coded input. Source files live under
// `frontend/`; hashed output and the manifest land under `static/build/`.
export default defineConfig({
  plugins: [tailwindcss()],
  build: {
    outDir: "static/build",
    emptyOutDir: true,
    manifest: true,
    rollupOptions: {
      input: {
        main: "frontend/main.js",
      },
    },
  },
});
