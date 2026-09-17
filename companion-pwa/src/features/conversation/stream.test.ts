import { createFrameParser, frameFromData } from './stream'

function frameChunk(seq: number, kind: string, isTerminal = false, payload: Record<string, unknown> = {}): string {
  return `id: ${seq}\nevent: ${kind}\ndata: ${JSON.stringify({ seq, kind, payload, is_terminal: isTerminal })}\n\n`
}

describe('frameFromData', () => {
  it('合法帧解析出 seq / kind / payload / is_terminal', () => {
    const frame = frameFromData(
      JSON.stringify({ seq: 3, kind: 'tool.call', payload: { tool_key: 'fs.read' }, is_terminal: false }),
    )
    expect(frame).toEqual({ seq: 3, kind: 'tool.call', payload: { tool_key: 'fs.read' }, is_terminal: false })
  })

  it('坏 JSON / 非对象 / 缺 seq 一律丢弃（不让一帧坏掉整条流）', () => {
    expect(frameFromData('{bad json')).toBeNull()
    expect(frameFromData('"just-text"')).toBeNull()
    expect(frameFromData(JSON.stringify({ kind: 'tool.call' }))).toBeNull()
  })

  it('缺 kind 时回落 SSE 事件名；未知 kind 原样保留（不猜测、不改写）', () => {
    expect(frameFromData(JSON.stringify({ seq: 1 }), 'run.paused')?.kind).toBe('run.paused')
    expect(frameFromData(JSON.stringify({ seq: 1, kind: 'future.event' }))?.kind).toBe('future.event')
  })
})

describe('createFrameParser', () => {
  it('增量喂入：心跳不产生帧，坏帧只丢自己、不影响后续帧', () => {
    const frames: number[] = []
    const discarded: string[] = []
    const parser = createFrameParser(
      (frame) => frames.push(frame.seq),
      (reason) => discarded.push(reason),
    )

    parser.feed(': hb\n\n')
    parser.feed(frameChunk(1, 'tool.call'))
    parser.feed('id: 2\nevent: tool.result\ndata: not-json\n\n')
    parser.feed(frameChunk(3, 'run.completed', true))

    expect(frames).toEqual([1, 3])
    expect(discarded).toEqual(['bad_frame'])
  })
})