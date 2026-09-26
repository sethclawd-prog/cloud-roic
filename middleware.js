// Vercel Edge Middleware: HTTP basic auth over the whole site. The password comes from the REVIEW_PASSWORD env var;
// any username works. The same page is public on GitHub Pages; this gate is for the Vercel review copy only.
export const config = { matcher: "/(.*)" };
export default function middleware(request) {
  const expected = process.env.REVIEW_PASSWORD;
  if (!expected) return;
  const header = request.headers.get("authorization") || "";
  if (header.startsWith("Basic ")) {
    try {
      const [, pass] = atob(header.slice(6)).split(":");
      if (pass === expected) return;
    } catch {}
  }
  return new Response("Cloud ROIC review: sign in with any username and the review password.", {
    status: 401, headers: { "WWW-Authenticate": 'Basic realm="Cloud ROIC", charset="UTF-8"' },
  });
}
