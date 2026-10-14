export interface SourceStatus {
  mode: 'authoritative' | 'fixture'
  freshness: 'current' | 'stale' | 'unknown'
  generated_at?: string | null
  age_seconds?: number | null
  problem?: string
}

export interface Evidence {
  id: string
  source?: { name?: string; domain?: string; semantic?: string; state_kind?: string }
  observed_at?: string | null
  freshness?: { status?: string; age_seconds?: number | null }
  confidence?: number
}

export interface WhyCheck {
  check: string
  result: 'pass' | 'fail' | 'unknown'
  detail: string
  source_ids: string[]
}

export interface Opportunity {
  opportunity_id: string
  action_id: string
  project_id?: string | null
  state: string
  action: Record<string, unknown>
  capacity?: Record<string, unknown> | null
  affordances: { required?: string[]; available?: string[]; missing?: string[]; providers?: string[] }
  why: WhyCheck[]
  warnings: string[]
}

export interface Machine {
  id: string
  label: string
  scope: string
  lifecycle?: string
  readiness?: string
  runtime?: string
  freshness?: string
  capabilities?: string[]
  evidence?: string[]
  why?: string[]
}

export interface Transition {
  situation_id: string
  action_id?: string | null
  from?: string | null
  to?: string | null
  changed_at?: string
  cause?: string
  source_ids?: string[]
}

export interface WorldState {
  generated_at: string
  source: SourceStatus
  inputs: Record<string, { generated_at?: string | null; contract?: { name?: string; schema_version?: string } | null }>
  opportunities: Opportunity[]
  machines: Machine[]
  capabilities: unknown[]
  transitions: Transition[]
  evidence_index: Evidence[]
  boundaries: string[]
}

export function explicitState(value: unknown): string {
  return typeof value === 'string' && value.trim() ? value : 'unknown'
}

export function sourceMessage(source: Pick<SourceStatus, 'mode' | 'freshness'>): string {
  if (source.mode === 'fixture') return 'Sanitized fixture — authoritative state unavailable'
  if (source.freshness === 'stale') return 'Authoritative snapshot is stale — not evidence that machines are offline'
  if (source.freshness === 'unknown') return 'Authoritative snapshot age is unknown'
  return 'Current authoritative snapshot'
}

export function evidenceAnchor(id: string): string {
  const safe = id.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
  return `evidence-${safe || 'unknown'}`
}

export interface RefreshState {
  world: WorldState | null
  error: string
  loading: boolean
  refreshing: boolean
}

interface FetchResponse {
  ok: boolean
  status?: number
  json: () => Promise<WorldState>
}

export interface WorldStateRefreshOptions {
  fetcher: () => Promise<FetchResponse>
  onUpdate: (state: RefreshState) => void
  schedule?: (callback: () => void, intervalMs: number) => unknown
  cancel?: (timer: unknown) => void
  intervalMs?: number
}

export function createWorldStateRefresh(options: WorldStateRefreshOptions) {
  let world: WorldState | null = null
  let timer: unknown = null
  const schedule = options.schedule ?? ((callback, intervalMs) => window.setInterval(callback, intervalMs))
  const cancel = options.cancel ?? ((handle) => window.clearInterval(handle as number))
  const intervalMs = options.intervalMs ?? 60_000

  const update = (error: string, loading: boolean, refreshing: boolean) => {
    options.onUpdate({ world, error, loading, refreshing })
  }

  const refresh = async () => {
    update('', world === null, world !== null)
    try {
      const response = await options.fetcher()
      if (!response.ok) throw new Error(`API returned ${response.status ?? 'an error'}`)
      world = await response.json()
      update('', false, false)
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : 'Unknown API error'
      update(message, false, false)
    }
  }

  return {
    async start() {
      await refresh()
      timer = schedule(() => { void refresh() }, intervalMs)
    },
    refresh,
    stop() {
      if (timer !== null) cancel(timer)
      timer = null
    },
  }
}
