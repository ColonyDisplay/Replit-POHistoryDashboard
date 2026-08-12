"use client";

import { useEffect, useState } from "react";
import { ClerkProvider, Show, SignIn, useAuth } from "@clerk/react";
import { publishableKeyFromHost } from "@clerk/react/internal";
import App from "./App";
import { setAuthTokenGetter } from "./api";

// REQUIRED — resolves the key from window.location.hostname so the same
// build serves the deployment domain; falls back to the env key.
const clerkPubKey = publishableKeyFromHost(
  window.location.hostname,
  process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY,
);

// Empty in dev (Clerk dev FAPI is reached directly), auto-set in prod.
const clerkProxyUrl = process.env.NEXT_PUBLIC_CLERK_PROXY_URL;

const clerkAppearance = {
  variables: {
    colorPrimary: "#2563eb",
    fontFamily: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
    borderRadius: "10px",
  },
};

// Bridges Clerk's session token into the plain fetch helpers in api.js.
function AuthTokenBridge() {
  const { getToken } = useAuth();
  useEffect(() => {
    setAuthTokenGetter(getToken);
    return () => setAuthTokenGetter(null);
  }, [getToken]);
  return null;
}

// Renders a visible loading spinner while Clerk initializes, and a clear
// error message if it never finishes — so the page can never be silently
// blank while auth is stalled or broken.
function ClerkGate({ children }) {
  const { isLoaded } = useAuth();
  const [timedOut, setTimedOut] = useState(false);

  useEffect(() => {
    if (isLoaded) return undefined;
    const t = setTimeout(() => setTimedOut(true), 20000);
    return () => clearTimeout(t);
  }, [isLoaded]);

  if (isLoaded) return children;

  return (
    <div
      style={{
        minHeight: "100dvh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: "1rem",
        padding: "1rem",
        textAlign: "center",
      }}
    >
      {timedOut ? (
        <>
          <h1 style={{ margin: 0, fontSize: "1.25rem" }}>
            Sign-in service failed to load
          </h1>
          <p style={{ margin: 0, color: "#64748b", maxWidth: "28rem" }}>
            The authentication service did not respond. Check your network
            connection, then reload the page. If the problem persists, contact
            your administrator.
          </p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            style={{
              padding: "0.5rem 1.25rem",
              borderRadius: "8px",
              border: "none",
              background: "#2563eb",
              color: "#fff",
              fontSize: "0.95rem",
              cursor: "pointer",
            }}
          >
            Reload
          </button>
        </>
      ) : (
        <>
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
        </>
      )}
    </div>
  );
}

function SignInScreen() {
  return (
    <div
      style={{
        minHeight: "100dvh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: "1.5rem",
        padding: "1rem",
      }}
    >
      <div style={{ textAlign: "center" }}>
        <h1 style={{ margin: 0, fontSize: "1.5rem" }}>Colony PO Dashboard</h1>
        <p style={{ margin: "0.5rem 0 0", color: "#64748b" }}>
          Sign in with your colonydisplay.com account
        </p>
      </div>
      <SignIn routing="hash" withSignUp appearance={clerkAppearance} />
    </div>
  );
}

export default function ClerkRoot() {
  if (!clerkPubKey) {
    return (
      <div style={{ padding: "2rem", textAlign: "center" }}>
        <h1 style={{ fontSize: "1.25rem" }}>Sign-in is not configured</h1>
        <p style={{ color: "#64748b" }}>
          Missing Clerk publishable key — contact your administrator.
        </p>
      </div>
    );
  }

  return (
    <ClerkProvider
      publishableKey={clerkPubKey}
      proxyUrl={clerkProxyUrl}
      appearance={clerkAppearance}
      afterSignOutUrl="/"
    >
      <ClerkGate>
        <Show when="signed-in">
          <AuthTokenBridge />
          <App />
        </Show>
        <Show when="signed-out">
          <SignInScreen />
        </Show>
      </ClerkGate>
    </ClerkProvider>
  );
}
