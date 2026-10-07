import type { SessionContextBreakdown } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'

import { allocate, toSnapshot } from '../hooks/register'

const breakdown = (total: number): SessionContextBreakdown => ({
  categories: [
    { name: 'System prompt', tokens: 4000, color: 'promptBorder', isDeferred: false, kind: 'used' },
    { name: 'System tools', tokens: 16000, color: 'inactive', isDeferred: false, kind: 'used' },
    { name: 'Messages', tokens: total - 20000, color: 'permission', isDeferred: false, kind: 'used' },
    { name: 'MCP tools (deferred)', tokens: 9000, color: 'inactive', isDeferred: true, kind: 'deferred' },
    { name: 'Autocompact buffer', tokens: 33000, color: 'warning', isDeferred: false, kind: 'buffer' },
    { name: 'Free space', tokens: 167000 - total, color: 'inactive', isDeferred: false, kind: 'free' },
  ],
  totalTokens: total, maxTokens: 200_000, rawMaxTokens: 200_000, autocompactSource: 'auto',
  percentage: Math.round((total / 200_000) * 100), gridRows: [], model: 'm',
  memoryFiles: [], mcpTools: [], agents: [], isAutoCompactEnabled: true, apiUsage: null,
})

test('allocate fills the width exactly and keeps tiny used rows visible', async () => {
  const cells = allocate(
    [
      { name: 'a', tokens: 10, color: 'x', kind: 'used' },
      { name: 'b', tokens: 50000, color: 'x', kind: 'used' },
      { name: 'free', tokens: 150000, color: 'x', kind: 'free' },
    ],
    40,
  )
  expect(cells.reduce((s, c) => s + c, 0)).toBe(40)
  expect(cells[0]).toBe(1)
})

test('toSnapshot drops deferred rows and orders used, buffer, free', async () => {
  const snap = toSnapshot(breakdown(60000))
  expect(snap.segments.map(s => s.name)).toEqual(['Messages', 'System tools', 'System prompt', 'Autocompact buffer', 'Free space'])
  expect(snap.percent).toBe(30)
})

test('the band shows the fill and each used category', async ($, on) => {
  on('ui.render', ($, e) => { const { Text } = $.ui.resolve(e); return <Text>ENGINE</Text> })
  mock.clock(on)
  on('session.usage', () => ({ value: { startedAt: 0, rateLimits: [], context: { window: 200_000, breakdown: breakdown(60000) } } }))
  const run = (($ as any).command.run) as (e: unknown) => Promise<unknown>
  await run({ command: 'ctx', args: '', origin: 'user' })
  await run({ command: 'ctx', args: '', origin: 'user' })
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'context-strip', surface, component: 'AbovePrompt', props: {} as never })
    expect(await ui.find({ type: 'Text', text: /ENGINE/ })).toBeUndefined()
    expect(await ui.find({ type: 'Text', text: /30%/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /Messages 40k/ })).toBeDefined()
    await ui.unmount()
  }
})
