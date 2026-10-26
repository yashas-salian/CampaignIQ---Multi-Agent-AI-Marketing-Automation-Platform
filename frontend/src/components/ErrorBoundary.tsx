import { Component, type ErrorInfo, type ReactNode } from 'react'

import { reportError } from '../lib/monitoring'

/** Last line of defence: a crash in one page shows a recovery screen instead of a blank app. */
export default class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    reportError(error, { componentStack: info.componentStack })
  }

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <div role="alert" style={{ minHeight: '60vh', display: 'grid', placeItems: 'center', padding: 24, textAlign: 'center' }}>
        <div style={{ maxWidth: 420, display: 'grid', gap: 12 }}>
          <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 26, margin: 0 }}>Something went wrong.</h1>
          <p style={{ color: 'var(--ciq-text-muted)', margin: 0, lineHeight: 1.6 }}>
            The error has been reported. Reloading usually fixes it; your campaigns are safe on the server.
          </p>
          <div>
            <button
              type="button"
              onClick={() => window.location.reload()}
              style={{ height: 44, padding: '0 22px', borderRadius: 12, border: 0, background: 'var(--ciq-accent)', color: '#111316', fontWeight: 600, cursor: 'pointer' }}
            >
              Reload
            </button>
          </div>
        </div>
      </div>
    )
  }
}
