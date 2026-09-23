// Liveness of the frontend server itself (used by the container health check).
// Route Handlers are not cached by default in this Next.js version.
export function GET() {
  return Response.json({ status: "ok" });
}
