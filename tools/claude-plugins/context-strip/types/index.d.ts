export type Segment = { name: string; tokens: number; color: string; kind: 'used' | 'free' | 'buffer' }
export type Snapshot = { total: number; max: number; percent: number; segments: Segment[] }

declare module 'claude-code' {
  interface PluginState {
    'context-strip': { snapshot: Snapshot | null; isHidden: boolean }
  }
}
