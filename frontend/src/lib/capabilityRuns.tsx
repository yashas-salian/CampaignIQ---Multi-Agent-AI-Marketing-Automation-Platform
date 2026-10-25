import type { ReactNode } from 'react'

// Shared by Tools (run + recent runs) and Tools history (every run, searchable).
export const CAPABILITIES = ['feasibility', 'decision', 'crash_test', 'personas', 'image'] as const
export type Capability = (typeof CAPABILITIES)[number]
export type RunStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface Run {
  id: string
  capability: string
  status: RunStatus
  params: Record<string, unknown>
  result: unknown
  error: string | null
  created_at: string
}

export const RUN_COLUMNS = 'id,capability,status,params,result,error,created_at'

export const isCapability = (c: string): c is Capability => (CAPABILITIES as readonly string[]).includes(c)

/** What the user typed for a run (the idea, or the image prompt). */
export const runInput = (run: Run) => String(run.params.idea ?? run.params.prompt ?? '')

export const CAP_META: Record<Capability, { title: string; desc: string; icon: ReactNode }> = {
  feasibility: {
    title: 'tl.capFeasibility',
    desc: 'tl.capFeasibilityDesc',
    icon: <path d="M4 19V5M4 19h16M8 15l4-4 3 3 5-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />,
  },
  decision: {
    title: 'tl.capDecision',
    desc: 'tl.capDecisionDesc',
    icon: (
      <>
        <path d="M12 3v4M12 17v4M5 12H3M21 12h-2" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        <circle cx="12" cy="12" r="5" stroke="currentColor" strokeWidth="2" />
        <path d="M10 12l1.5 1.5L14.5 10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </>
    ),
  },
  crash_test: {
    title: 'tl.capCrash',
    desc: 'tl.capCrashDesc',
    icon: (
      <>
        <path d="M12 3l8 4v5c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V7z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
        <path d="M12 8v5M12 16v.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      </>
    ),
  },
  personas: {
    title: 'tl.capPersonas',
    desc: 'tl.capPersonasDesc',
    icon: (
      <>
        <circle cx="9" cy="8" r="3.5" stroke="currentColor" strokeWidth="2" />
        <path d="M2.5 20c1-3.5 3.6-5.5 6.5-5.5s5.5 2 6.5 5.5M16 4.5a3.5 3.5 0 0 1 0 7M18 14.8c1.8.7 3 2.5 3.5 5.2" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      </>
    ),
  },
  image: {
    title: 'tl.capImage',
    desc: 'tl.capImageDesc',
    icon: (
      <>
        <rect x="3" y="4" width="18" height="16" rx="2" stroke="currentColor" strokeWidth="2" />
        <path d="M3 15l5-5 4 4 3-3 6 6" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
        <circle cx="15.5" cy="8.5" r="1.5" fill="currentColor" />
      </>
    ),
  },
}
