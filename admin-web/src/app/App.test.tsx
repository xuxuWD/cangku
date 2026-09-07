import { render, screen, waitFor } from '@testing-library/react'
import App from './App'

describe('App', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input)
      return { ok: true, json: async () => path.includes('/audits') ? [] : { binding_type: 'role', binding_key: 'content-operator', knowledge_base_ids: ['company-general'] } } as Response
    }))
  })
  afterEach(() => vi.unstubAllGlobals())

  it('shows the Chinese content workbench entry point', () => {
    render(<App />)
    return waitFor(() => {
      expect(screen.getByRole('heading', { name: '内容工作台' })).toBeInTheDocument()
      expect(screen.getByText('素材输入')).toBeInTheDocument()
      expect(screen.getByText('草稿预览')).toBeInTheDocument()
    })
  })
})
