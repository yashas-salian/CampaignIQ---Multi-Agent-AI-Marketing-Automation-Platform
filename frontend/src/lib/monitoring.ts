// Browser error tracking. Sentry is loaded only when VITE_SENTRY_DSN is set,
// so builds without it don't download the SDK at all.
const dsn = import.meta.env.VITE_SENTRY_DSN as string | undefined

type SentryModule = typeof import('@sentry/react')
let sentry: Promise<SentryModule> | null = null

export function initMonitoring() {
  if (!dsn) return
  sentry = import('@sentry/react').then((Sentry) => {
    Sentry.init({
      dsn,
      release: `campaigniq@${__APP_VERSION__}`,
      environment: import.meta.env.MODE,
      tracesSampleRate: 0,
    })
    return Sentry
  })
}

export function reportError(error: unknown, context?: Record<string, unknown>) {
  console.error(error)
  sentry?.then((Sentry) => Sentry.captureException(error, { extra: context }))
}
