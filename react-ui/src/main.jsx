import { StrictMode, useEffect } from 'react'
import { createRoot } from 'react-dom/client'
import {
  ClerkProvider,
  Show,
  SignIn,
  useAuth,
} from '@clerk/react'
import { publishableKeyFromHost } from '@clerk/react/internal'
import './index.css'
import App from './App.jsx'
import { setAuthTokenGetter } from './api.js'

// REQUIRED — resolves the key from window.location.hostname so the same
// build serves the deployment domain; falls back to the env key.
const clerkPubKey = publishableKeyFromHost(
  window.location.hostname,
  import.meta.env.VITE_CLERK_PUBLISHABLE_KEY,
)

// Empty in dev (Clerk dev FAPI is reached directly), auto-set in prod.
const clerkProxyUrl = import.meta.env.VITE_CLERK_PROXY_URL

if (!clerkPubKey) {
  throw new Error('Missing VITE_CLERK_PUBLISHABLE_KEY')
}

const clerkAppearance = {
  variables: {
    colorPrimary: '#2563eb',
    fontFamily:
      "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
    borderRadius: '10px',
  },
}

// Bridges Clerk's session token into the plain fetch helpers in api.js.
function AuthTokenBridge() {
  const { getToken } = useAuth()
  useEffect(() => {
    setAuthTokenGetter(getToken)
    return () => setAuthTokenGetter(null)
  }, [getToken])
  return null
}

function SignInScreen() {
  return (
    <div
      style={{
        minHeight: '100dvh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: '1.5rem',
        padding: '1rem',
      }}
    >
      <div style={{ textAlign: 'center' }}>
        <h1 style={{ margin: 0, fontSize: '1.5rem' }}>Colony PO Dashboard</h1>
        <p style={{ margin: '0.5rem 0 0', color: '#64748b' }}>
          Sign in with your colonydisplay.com account
        </p>
      </div>
      <SignIn routing="hash" appearance={clerkAppearance} />
    </div>
  )
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ClerkProvider
      publishableKey={clerkPubKey}
      proxyUrl={clerkProxyUrl}
      appearance={clerkAppearance}
      afterSignOutUrl="/"
    >
      <Show when="signed-in">
        <AuthTokenBridge />
        <App />
      </Show>
      <Show when="signed-out">
        <SignInScreen />
      </Show>
    </ClerkProvider>
  </StrictMode>,
)
