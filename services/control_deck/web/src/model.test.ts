import { describe, expect, it } from 'vitest'
import { evidenceAnchor, explicitState, sourceMessage } from './model'

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
})
