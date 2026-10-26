// Same-origin relay for the public demo dashboard.
export default async function handler(request, response) {
  response.setHeader("Cache-Control", "no-store");
  const route = request.query?.path;
  const path = Array.isArray(route) ? route.join("/") : typeof route === "string" ? route
    : new URL(request.url, "https://dashboard.invalid").pathname.replace(/^\/api\//, "");
  const allowed = (request.method === "GET" && /^(health|centers|transfers\/[a-f0-9]{10})$/.test(path))
    || (request.method === "POST" && /^(transfers|transfers\/[a-f0-9]{10}\/accept)$/.test(path));
  if (!allowed) return response.status(404).json({ detail: "Unknown dashboard endpoint." });
  const origin = process.env.UZIMA_BACKEND_URL;
  if (!origin) return response.status(503).json({ detail: "The demo backend is not configured." });
  try {
    const result = await fetch(`${origin.replace(/\/$/, "")}/dashboard/${path}`, {
      method: request.method,
      headers: { "Content-Type": "application/json", ...demoPhone(request, path) },
      body: request.method === "POST" ? JSON.stringify(request.body) : undefined,
      signal: AbortSignal.timeout(50000),
      redirect: "error",
    });
    if (result.status === 503) return response.status(503).json({ detail: "The demo backend is offline. Please try again shortly." });
    response.setHeader("Content-Type", "application/json");
    return response.status(result.status).send(await result.text());
  } catch {
    return response.status(503).json({ detail: "The demo backend is offline. Please try again shortly." });
  }
}

// A visitor's own number for the first hospital call travels only with a new search.
function demoPhone(request, path) {
  const phone = path === "transfers" ? request.headers?.["x-uzima-demo-phone"] : undefined;
  return typeof phone === "string" && phone ? { "X-Uzima-Demo-Phone": phone.slice(0, 32) } : {};
}
