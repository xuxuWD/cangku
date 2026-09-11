import { applyTheme, isThemeMode, readStoredMode, resolveTheme, writeStoredMode } from './theme'

describe('theme', () => {
  it('recognises only the three supported modes', () => {
    expect(isThemeMode('light')).toBe(true)
    expect(isThemeMode('dark')).toBe(true)
    expect(isThemeMode('system')).toBe(true)
    expect(isThemeMode('neon')).toBe(false)
    expect(isThemeMode(undefined)).toBe(false)
  })

  it('falls back to 跟随系统 when nothing usable is stored', () => {
    expect(readStoredMode(undefined)).toBe('system')
    expect(readStoredMode({ getItem: () => null })).toBe('system')
    expect(readStoredMode({ getItem: () => 'neon' })).toBe('system')
  })

  it('reads a stored mode back', () => {
    expect(readStoredMode({ getItem: () => 'dark' })).toBe('dark')
  })

  it('does not break the page when storage throws', () => {
    const broken = {
      getItem: () => { throw new Error('storage disabled') },
      setItem: () => { throw new Error('storage disabled') },
    }
    expect(readStoredMode(broken)).toBe('system')
    expect(() => writeStoredMode('dark', broken)).not.toThrow()
  })

  it('resolves 跟随系统 against the system preference', () => {
    expect(resolveTheme('system', true)).toBe('dark')
    expect(resolveTheme('system', false)).toBe('light')
    expect(resolveTheme('dark', false)).toBe('dark')
    expect(resolveTheme('light', true)).toBe('light')
  })

  it('writes the resolved theme onto the root element', () => {
    const root = document.createElement('html')
    applyTheme('dark', root)
    expect(root.dataset.theme).toBe('dark')
    applyTheme('light', root)
    expect(root.dataset.theme).toBe('light')
  })

  it('persists the chosen mode', () => {
    const store = new Map<string, string>()
    writeStoredMode('dark', { setItem: (key, value) => { store.set(key, value) } })
    expect(store.get('workbench.theme')).toBe('dark')
  })
})
