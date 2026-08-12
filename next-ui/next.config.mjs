/** @type {import('next').NextConfig} */
const nextConfig = {
  // Static export — the FastAPI backend serves next-ui/out just like it
  // served react-ui/dist. No Next server runs in production.
  output: "export",
  images: { unoptimized: true },
  env: {
    // Replit-managed Clerk provisions the VITE_-prefixed vars; map them to
    // NEXT_PUBLIC_ so they inline into the client bundle at build time.
    // VITE_CLERK_PROXY_URL is intentionally empty in dev (Clerk dev FAPI is
    // reached directly) and auto-populated in production deploy builds.
    NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY:
      process.env.VITE_CLERK_PUBLISHABLE_KEY ||
      process.env.CLERK_PUBLISHABLE_KEY ||
      "",
    NEXT_PUBLIC_CLERK_PROXY_URL: process.env.VITE_CLERK_PROXY_URL || "",
  },
};

export default nextConfig;
