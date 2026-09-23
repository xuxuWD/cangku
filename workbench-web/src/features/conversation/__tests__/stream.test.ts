import { createFrameParser, frameFromData } from '../stream'
import type { StreamFrame } from '../types'

describe('frameFromData', () => {
  it('parses the contract frame shape', () => {
    const frame = frameFromData('{"seq":3,"kind":"tool.call","payload":{"tool_key":"cmd.run"},"is_terminal":false}')
    expect(frame).toEqual({ seq: 3, kind: 'tool.call', payload: { tool_key: 'cmd.run' }, is_terminal: false })
  })

  it('drops bad JSON and structurally invalid frames instead of breaking the stream', () => {
    expect(frameFromData('not json')).toBeNull()
    expect(frameFromData('[]')).toBeNull()
    expect(frameFromData('{"kind":"tool.call"}')).toBeNull() // 缺 seq
    expect(frameFromData('{"seq":"abc"}')).toBeNull()
  })

  it('falls back to the SSE event name when data carries no kind', () => {
    const frame = frameFromData('{"seq":1,"payload":{},"is_terminal":false}', 'run.completed')
    expect(frame?.kind).toBe('run.completed')
  })

  it('parses the additive run_id field (absent when the server omits it)', () => {
    const withRun = frameFromData('{"run_id":"run-1","seq":3,"kind":"tool.call","payload":{},"is_terminal":false}')
    expect(withRun?.run_id).toBe('run-1')
    const without = frameFromData('{"seq":3,"kind":"tool.call","payload":{},"is_terminal":false}')
    expect(without && 'run_id' in without).toBe(false)
  })
})

function collect(): { frames: StreamFrame[]; feed: (chunk: string) => void; discarded: string[] } {
  const frames: StreamFrame[] = []
  const discarded: string[] = []
  const parser = createFrameParser(
    (frame) => frames.push(frame),
    (reason) => discarded.push(reason),
  )
  return { frames, feed: parser.feed, discarded }
}

describe('createFrameParser', () => {
  it('handles events split across chunks (including multi-byte text)', () => {
    const { frames, feed } = collect()
    feed('id: 1\nevent: tool.call\ndata: {"seq":1,"kind":"tool.call","payload":{"step_id":"步骤')
    feed('-1"},"is_terminal":false}\n\n')
    expect(frames).toHaveLength(1)
    expect(frames[0]).toMatchObject({ seq: 1, kind: 'tool.call' })
    expect((frames[0].payload as { step_id: string }).step_id).toBe('步骤-1')
  })

  it('ignores heartbeat comments and does not emit them as events', () => {
    const { frames, feed } = collect()
    feed(': hb\n\n: hb\n\n')
    feed('id: 2\nevent: run.completed\ndata: {"seq":2,"kind":"run.completed","payload":{},"is_terminal":true}\n\n')
    expect(frames.map((frame) => frame.kind)).toEqual(['run.completed'])
  })

  it('counts a discarded frame but keeps parsing the following ones', () => {
    const { frames, feed, discarded } = collect()
    feed('id: 1\nevent: tool.call\ndata: {oops\n\n')
    feed('id: 2\nevent: run.completed\ndata: {"seq":2,"kind":"run.completed","payload":{},"is_terminal":true}\n\n')
    expect(discarded).toEqual(['bad_frame'])
    expect(frames.map((frame) => frame.seq)).toEqual([2])
  })

  it('carries unknown kinds through unchanged (前端不猜测语义)', () => {
    const { frames, feed } = collect()
    feed('id: 9\nevent: future.event\ndata: {"seq":9,"kind":"future.event","payload":{"x":1},"is_terminal":false}\n\n')
    expect(frames[0].kind).toBe('future.event')
  })
})