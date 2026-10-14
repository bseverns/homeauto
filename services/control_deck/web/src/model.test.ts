import { describe, expect, it, vi } from 'vitest'
import { createWorldStateRefresh, evidenceAnchor, explicitState, sourceMessage, type WorldState } from './model'

describe('control deck presentation model', () => {
  it('keeps stale source evidence distinct from offline machines', () => {
    expect(sourceMessage({ mode: 'authoritative', freshness: 'stale' })).toContain('stale')
    expect(sourceMessage({ mode: 'authoritative', freshness: 'stale' })).toContain('not evidence that machines are offline')
  })

  it('renders missing values explicitly', () => {
    expect(explicitState(undefined)).toBe('unknown')
    expect(explicitState('')).toBe('unknown')
    expect(explicitState('unavailable')).toBe('unavailable')
  })

  it('creates local evidence anchors without exposing paths', () => {
    expect(evidenceAnchor('observation:studio health/one')).toBe('evidence-observation-studio-health-one')
    expect(evidenceAnchor('/private/path')).not.toContain('/')
  })

  it('preserves the last successful state when a refresh fails', async () => {
    const world = { generated_at: '2026-10-13T12:00:00Z' } as WorldState
    const fetcher = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => world })
      .mockRejectedValueOnce(new Error('network unavailable'))
    const states: Array<{ world: WorldState | null; error: string; loading: boolean; refreshing: boolean }> = []
    const scheduled: Array<() => void> = []
    const cancelled: unknown[] = []
    const refresh = createWorldStateRefresh({
      fetcher,
      onUpdate: (state) => states.push(state),
      schedule: (callback) => { scheduled.push(callback); return 'timer' },
      cancel: (timer) => { cancelled.push(timer) },
    })

    await refresh.start()
    await refresh.refresh()
    refresh.stop()

    expect(fetcher).toHaveBeenCalledTimes(2)
    expect(scheduled).toHaveLength(1)
    expect(cancelled).toEqual(['timer'])
    expect(states.at(-1)).toEqual({
      world,
      error: 'network unavailable',
      loading: false,
      refreshing: false,
    })
  })
})
