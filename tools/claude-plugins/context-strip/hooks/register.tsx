import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, SessionContextBreakdown } from 'claude-code'

import type { Segment, Snapshot } from '../types'

const snapshot = atom({ plugin: 'context-strip', key: 'snapshot' } as const, null)
const isHidden = atom({ plugin: 'context-strip', key: 'isHidden' } as const, false)

const WIDTH = 40
const REFRESH_MS = 3000

export function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 10_000) return `${Math.round(n / 1000)}k`
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return String(Math.round(n))
}

/** Splits `width` cells over the segments by largest remainder; any non-empty used row gets at least one. */
export function allocate(segments: Segment[], width: number): number[] {
  const sum = segments.reduce((s, x) => s + x.tokens, 0)
  if (sum <= 0) return segments.map(() => 0)
  const exact = segments.map(x => (x.tokens / sum) * width)
  const cells = exact.map((v, i) => (segments[i]!.kind === 'used' && segments[i]!.tokens > 0 ? Math.max(1, Math.floor(v)) : Math.floor(v)))
  let left = width - cells.reduce((s, c) => s + c, 0)
  const order = exact.map((v, i) => ({ i, r: v - Math.floor(v) })).sort((a, b) => b.r - a.r)
  for (let k = 0; left > 0 && order.length > 0; k = (k + 1) % order.length, left--) cells[order[k]!.i]! += 1
  // Taking back cells the minimum overspent, from the largest rows first.
  while (left < 0) {
    let big = 0
    cells.forEach((c, i) => { if (c > cells[big]!) big = i })
    cells[big]! -= 1
    left++
  }
  return cells
}

export function toSnapshot(b: SessionContextBreakdown): Snapshot {
  const segments: Segment[] = []
  for (const c of b.categories) {
    if (c.kind === 'deferred' || c.tokens <= 0) continue
    segments.push({ name: c.name, tokens: c.tokens, color: c.color, kind: c.kind })
  }
  // Used rows first, largest first; then the buffer; free space last.
  const rank = { used: 0, buffer: 1, free: 2 } as const
  segments.sort((a, x) => rank[a.kind] - rank[x.kind] || (a.kind === 'used' ? x.tokens - a.tokens : 0))
  return { total: b.totalTokens, max: b.rawMaxTokens, percent: b.percentage, segments }
}

async function refresh($: EngineInterface): Promise<void> {
  const usage = await $.session.usage({ breakdown: 'summary' })
  const b = usage.context.breakdown
  if (!b) return
  const next = toSnapshot(b)
  await update($, snapshot, () => next)
}

let lastAt = 0

async function maybeRefresh($: EngineInterface, force = false): Promise<void> {
  try {
    const now = await $.clock.now()
    if (!force && now - lastAt < REFRESH_MS) return
    lastAt = now
    await refresh($)
  } catch {
    // A breakdown can be unavailable for a moment (no session bound yet); the next event retries.
  }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'ctx', description: 'Show or hide the context-fill strip' })
    const ran = await next(e)
    await maybeRefresh($, true)
    return ran
  })

  on('command.run', { command: 'ctx' }, async $ => {
    await update($, isHidden, v => !v)
    const hidden = await read($, isHidden)
    if (!hidden) await maybeRefresh($, true)
    return { text: (hidden ? 'Context strip hidden.' : 'Context strip shown.') }
  })

  on('prompt.submit', async ($, e, next) => {
    const ran = await next(e)
    void maybeRefresh($, true)
    return ran
  })

  on('tool.call', async ($, e, next) => {
    const ran = await next(e)
    void maybeRefresh($)
    return ran
  })

  on('turn.complete', async ($, e, next) => {
    const ran = await next(e)
    await maybeRefresh($, true)
    return ran
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const snap = await read($, snapshot)
    if (e.props.hasSurvey || snap === null || (await read($, isHidden))) return next(e)

    const { Box, Text } = $.ui.resolve(e)
    const cells = allocate(snap.segments, WIDTH)
    const used = snap.segments.filter(s => s.kind === 'used')
    const warn = snap.percent >= 85 ? 'error' : snap.percent >= 65 ? 'warning' : undefined

    return (
      <Box flexDirection="column">
        <Box>
          <Text key="bar">
            {snap.segments.map((s, i) =>
              s.kind === 'free'
                ? <Text dimColor>{'░'.repeat(cells[i]!)}</Text>
                : <Text color={s.color} dimColor={s.kind === 'buffer'}>{(s.kind === 'buffer' ? '▒' : '█').repeat(cells[i]!)}</Text>,
            )}
          </Text>
          <Text color={warn} bold={warn !== undefined}> {snap.percent}%</Text>
          <Text dimColor> {formatTokens(snap.total)}/{formatTokens(snap.max)}</Text>
        </Box>
        <Box flexWrap="wrap">
          {used.map(s => (
            <Text>
              <Text color={s.color}>■</Text>
              <Text dimColor> {s.name} {formatTokens(s.tokens)}  </Text>
            </Text>
          ))}
        </Box>
      </Box>
    )
  })
}
