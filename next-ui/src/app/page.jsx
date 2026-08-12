"use client";

import dynamic from "next/dynamic";

// Clerk resolves its publishable key from window.location.hostname, so the
// auth root must only render in the browser — never during static export.
const ClerkRoot = dynamic(() => import("../components/ClerkRoot"), {
  ssr: false,
  loading: () => (
    <div
      style={{
        minHeight: "100dvh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: "1rem",
      }}
    >
      <div
        aria-label="Loading"
        style={{
          width: "2.25rem",
          height: "2.25rem",
          border: "3px solid #e2e8f0",
          borderTopColor: "#2563eb",
          borderRadius: "50%",
          animation: "clerk-gate-spin 0.8s linear infinite",
        }}
      />
      <p style={{ margin: 0, color: "#64748b" }}>Loading…</p>
    </div>
  ),
});

export default function Home() {
  return <ClerkRoot />;
}
