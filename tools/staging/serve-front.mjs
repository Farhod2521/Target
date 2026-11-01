/* The site, the cabinet and the office on one address, as deploy/nginx.conf serves them: the office
   has no sign-in of its own and takes the cabinet's session, so they must share an origin.
   Build first in the frontend repo: VITE_API_URL=http://localhost:8200 node scripts/build-static.mjs
   Usage: node tools/staging/serve-front.mjs <dist-static> [port] */
import fs from "node:fs";
import http from "node:http";
import path from "node:path";

const [root, port = "8300"] = process.argv.slice(2);
const TYPES = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".map": "application/json",
  ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp", ".ico": "image/x-icon",
  ".woff2": "font/woff2", ".mp4": "video/mp4", ".mp3": "audio/mpeg", ".webmanifest": "application/manifest+json",
};

const spa = url => (/^\/(app|accounts)(\/|$)/.test(url) ? "_cabinet/index.html" : /^\/ofis(\/|$)/.test(url) ? "_office/index.html" : null);

http
  .createServer((req, res) => {
    const url = decodeURIComponent((req.url ?? "/").split("?")[0]);
    let file = path.join(root, path.normalize(spa(url) ?? url));
    if (!file.startsWith(path.resolve(root))) file = path.join(root, "index.html");
    if (fs.existsSync(file) && fs.statSync(file).isDirectory()) file = path.join(file, "index.html");
    if (!fs.existsSync(file)) file = path.join(root, "__spa-fallback.html");
    res.writeHead(200, { "Content-Type": TYPES[path.extname(file)] ?? "application/octet-stream", "Cache-Control": "no-cache" });
    fs.createReadStream(file).pipe(res);
  })
  .listen(Number(port), "127.0.0.1", () => console.log(`http://localhost:${port}`));
