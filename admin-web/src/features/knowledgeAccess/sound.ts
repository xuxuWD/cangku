export type UiSound = 'success' | 'warning' | 'error' | 'toggle'

let audioContext: AudioContext | null = null

function getAudioContext(): AudioContext | null {
  if (typeof window === 'undefined' || !('AudioContext' in window)) return null
  audioContext ??= new AudioContext()
  if (audioContext.state === 'suspended') void audioContext.resume()
  return audioContext
}

export function playUiSound(kind: UiSound): void {
  const context = getAudioContext()
  if (!context) return

  const notes: Record<UiSound, number[]> = {
    success: [660, 880],
    warning: [430, 360],
    error: [310, 240],
    toggle: [520],
  }
  const now = context.currentTime
  const gain = context.createGain()
  gain.gain.setValueAtTime(0.0001, now)
  gain.gain.exponentialRampToValueAtTime(0.035, now + 0.012)
  gain.gain.exponentialRampToValueAtTime(0.0001, now + (notes[kind].length > 1 ? 0.24 : 0.12))
  gain.connect(context.destination)

  notes[kind].forEach((frequency, index) => {
    const oscillator = context.createOscillator()
    const start = now + index * 0.075
    oscillator.type = 'sine'
    oscillator.frequency.setValueAtTime(frequency, start)
    oscillator.connect(gain)
    oscillator.start(start)
    oscillator.stop(start + 0.11)
  })
}
