"use client";

import dynamic from "next/dynamic";

const ClerkRoot = dynamic(() => import("../../components/ClerkRoot"), {
  ssr: false,
  loading: () => <div style={{ minHeight: "100dvh", display: "grid", placeItems: "center", color: "#64748b" }}>Loading…</div>,
});

export default function DataLakePage() {
  return <ClerkRoot initialPage="datalake" />;
}