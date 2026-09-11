import { clearSession, isSessionExpired, loadSession, saveSession, SESSION_STORAGE_KEY, type Session } from './session'

const sample: Session = {
  accessToken: 'token-abc',
  tenantId: 'tenant-1',
  userId: 'user-1',
  role: 'ceo',
  expiresAt: 2000,
}

describe('session storage', () => {
  beforeEach(() => localStorage.clear())

  it('saves and loads a valid session', () => {
    saveSession(sample)

    expect(loadSession()).toEqual(sample)
  })

  it('returns null when nothing is stored', () => {
    expect(loadSession()).toBeNull()
  })

  it('returns null and clears corrupted JSON', () => {
    localStorage.setItem(SESSION_STORAGE_KEY, '{not-json')

    expect(loadSession()).toBeNull()
    expect(localStorage.getItem(SESSION_STORAGE_KEY)).toBeNull()
  })

  it('returns null and clears structurally invalid payloads', () => {
    localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify({ accessToken: 'token-abc' }))

    expect(loadSession()).toBeNull()
    expect(localStorage.getItem(SESSION_STORAGE_KEY)).toBeNull()
  })

  it('judges expiry against the supplied clock', () => {
    expect(isSessionExpired(sample, 1999)).toBe(false)
    expect(isSessionExpired(sample, 2000)).toBe(true)
    expect(isSessionExpired(null, 0)).toBe(true)
  })

  it('removes the stored value on clearSession', () => {
    saveSession(sample)
    clearSession()

    expect(loadSession()).toBeNull()
  })
})
