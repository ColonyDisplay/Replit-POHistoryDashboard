"use client";

import { useCallback, useEffect, useState } from "react";
import { ClerkProvider, Show, SignIn, useAuth } from "@clerk/react";
import { publishableKeyFromHost } from "@clerk/react/internal";
import App from "./App";
import { setAuthTokenGetter } from "./api";
import { UI_BUILD_ID } from "../generated/uiBuildVersion";

// REQUIRED — resolves the key from window.location.hostname so the same
// build serves the deployment domain; falls back to the env key.
const clerkPubKey = process.env.NEXT_PUBLIC_VISUAL_TEST_MODE === "1"
  ? ""
  : publishableKeyFromHost(
    window.location.hostname,
    process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY,
  );

// Empty in dev (Clerk dev FAPI is reached directly), auto-set in prod.
const clerkProxyUrl = process.env.NEXT_PUBLIC_CLERK_PROXY_URL;

// Overrides the "Continue to <application name>" heading on the sign-in
// card (the app name itself lives in Clerk's dashboard and isn't editable
// for this managed instance).
const clerkLocalization = {
  signIn: {
    start: {
      title: "Colony Epicor Dashboard",
      titleCombined: "Colony Epicor Dashboard",
      subtitle: "Sign in with your colonydisplay.com account",
      subtitleCombined: "Sign in with your colonydisplay.com account",
    },
  },
};

const clerkAppearance = {
  variables: {
    colorPrimary: "#2563eb",
    fontFamily: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
    borderRadius: "10px",
  },
};

// Bridges Clerk's session token into the plain fetch helpers in api.js.
function AuthTokenBridge({ onReady }) {
  const { getToken } = useAuth();
  useEffect(() => {
    setAuthTokenGetter(getToken);
    onReady();
    return () => setAuthTokenGetter(null);
  }, [getToken, onReady]);
  return null;
}

function SignedInApp({ initialPage }) {
  const [tokenReady, setTokenReady] = useState(false);
  const markTokenReady = useCallback(() => setTokenReady(true), []);
  return (
    <>
      <AuthTokenBridge onReady={markTokenReady} />
      {tokenReady ? <App initialPage={initialPage} /> : null}
    </>
  );
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

function SignInScreen({ returnTo = "/" }) {
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
      <SignIn routing="hash" withSignUp appearance={clerkAppearance} forceRedirectUrl={returnTo} />
    </div>
  );
}

const PREVIEW_BUILD_RELOAD_KEY = "colony-preview-build-reload";
const PREVIEW_BUILD_CHECK_INTERVAL_MS = 60_000;

function usePreviewBuildRefresh(previewMode) {
  useEffect(() => {
    if (previewMode !== true) return undefined;

    let active = true;
    let checking = false;
    let reloadStarted = false;
    document.documentElement.dataset.uiBuildId = UI_BUILD_ID;

    const checkBuild = async () => {
      if (!active || checking || reloadStarted) return;
      checking = true;
      try {
        const response = await fetch(
          `/api/ui-version?client=${encodeURIComponent(UI_BUILD_ID)}&t=${Date.now()}`,
          {
            cache: "no-store",
            headers: { "Cache-Control": "no-cache" },
          },
        );
        if (!response.ok || !active) return;

        const payload = await response.json();
        const serverBuildId = typeof payload.buildId === "string"
          ? payload.buildId.trim()
          : "";
        if (!serverBuildId) return;

        if (serverBuildId === UI_BUILD_ID) {
          sessionStorage.removeItem(PREVIEW_BUILD_RELOAD_KEY);
          return;
        }

        // One attempt per server build prevents a malformed or partially copied
        // export from trapping Preview in a reload loop.
        if (sessionStorage.getItem(PREVIEW_BUILD_RELOAD_KEY) === serverBuildId) {
          return;
        }
        sessionStorage.setItem(PREVIEW_BUILD_RELOAD_KEY, serverBuildId);
        reloadStarted = true;
        window.location.reload();
      } catch {
        // A transient version-check failure must not interrupt the dashboard.
      } finally {
        checking = false;
      }
    };

    const checkWhenVisible = () => {
      if (document.visibilityState === "visible") checkBuild();
    };

    checkBuild();
    window.addEventListener("focus", checkBuild);
    document.addEventListener("visibilitychange", checkWhenVisible);
    const intervalId = window.setInterval(
      checkBuild,
      PREVIEW_BUILD_CHECK_INTERVAL_MS,
    );

    return () => {
      active = false;
      window.removeEventListener("focus", checkBuild);
      document.removeEventListener("visibilitychange", checkWhenVisible);
      window.clearInterval(intervalId);
      delete document.documentElement.dataset.uiBuildId;
    };
  }, [previewMode]);
}

export default function ClerkRoot({ initialPage = "home" }) {
  const [previewMode, setPreviewMode] = useState(null);
  usePreviewBuildRefresh(previewMode);
  const signInReturnTo = initialPage === "datalake"
    ? "/datalake"
    : initialPage === "admin"
      ? "/admin"
      : "/";

  useEffect(() => {
    let active = true;
    fetch("/api/preview-mode", { cache: "no-store" })
      .then((response) => response.ok ? response.json() : { enabled: false })
      .then((data) => {
        if (active) setPreviewMode(data.enabled === true);
      })
      .catch(() => {
        if (active) setPreviewMode(false);
      });
    return () => {
      active = false;
    };
  }, []);

  if (previewMode === null) {
    return (
      <div style={{ minHeight: "100dvh", display: "grid", placeItems: "center", color: "#64748b" }}>
        Loading preview…
      </div>
    );
  }

  if (previewMode && !clerkPubKey) {
    return <App previewMode initialPage={initialPage} />;
  }

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
      localization={clerkLocalization}
      afterSignOutUrl="/"
    >
      <ClerkGate>
        <Show when="signed-in">
          <SignedInApp initialPage={initialPage} />
        </Show>
        <Show when="signed-out">
          {previewMode ? <App previewMode initialPage={initialPage} /> : <SignInScreen returnTo={signInReturnTo} />}
        </Show>
      </ClerkGate>
    </ClerkProvider>
  );
}
