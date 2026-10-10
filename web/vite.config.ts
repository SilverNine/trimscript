import fs from "node:fs";
import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import license from "rollup-plugin-license";

// License texts of everything bundled into the editor, shipped next to it in the Python package.
// Rollup sees the JS dependencies; CSS-only packages and the vendored shadcn/ui components are added here.
const extra = [
  { name: "tailwindcss", license: "MIT", file: "node_modules/tailwindcss/LICENSE" },
  { name: "tw-animate-css", license: "MIT", file: "node_modules/tw-animate-css/LICENSE" },
  { name: "shadcn/ui (components copied into web/src/components/ui)", license: "MIT", file: "licenses/shadcn-ui.LICENSE.md" },
];

// npm packages published without their LICENSE file; the text comes from the upstream repository
const vendored: Record<string, string> = {
  "react-remove-scroll-bar": "licenses/react-remove-scroll-bar.LICENSE",
};

const block = (title: string, lic: string, text: string) => `${"=".repeat(78)}\n${title}\nLicense: ${lic}\n\n${text.trim()}\n`;

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    license({
      thirdParty: {
        includePrivate: false,
        output: {
          file: path.resolve(__dirname, "../src/trimscript/static/THIRD_PARTY_LICENSES.txt"),
          template(deps) {
            const missing: string[] = [];
            const head = "Third-party software bundled in the trimscript editor (src/trimscript/static).\n\n";
            const js = deps
              .sort((a, b) => (a.name ?? "").localeCompare(b.name ?? ""))
              .map((d) => {
                const own = d.name && vendored[d.name];
                if (!d.licenseText && own) d.licenseText = fs.readFileSync(path.resolve(__dirname, own), "utf8");
                if (!d.licenseText) missing.push(`${d.name}@${d.version} ${d.license} ${JSON.stringify(d.author ?? "")}`);
                const notice = d.noticeText ? `\n\nNOTICE:\n${d.noticeText.trim()}` : "";
                return block(`${d.name} ${d.version}`, d.license ?? "unknown", d.licenseText + notice);
              });
            const css = extra.map((e) => block(e.name, e.license, fs.readFileSync(path.resolve(__dirname, e.file), "utf8")));
            if (missing.length) throw new Error("no license text for:\n" + missing.join("\n"));
            return (head + [...js, ...css].join("\n")).replace(/\r\n?/g, "\n"); // some upstream texts use CRLF
          },
        },
      },
    }),
  ],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  build: { outDir: "../src/trimscript/static", emptyOutDir: true },
  server: {
    proxy: { "/api": "http://127.0.0.1:4747", "/media": "http://127.0.0.1:4747" },
  },
});
