import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'

describe('App', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/')
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

  it('renders the knowledge access page for the knowledge view', async () => {
    window.history.replaceState({}, '', '/?view=knowledge')

    render(<App />)

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: '知识权限管理' })).toBeInTheDocument()
      expect(screen.getByText('可以使用的知识库')).toBeInTheDocument()
    })
  })

  it('navigates to the knowledge access page from the sidebar', async () => {
    const user = userEvent.setup()
    render(<App />)

    await user.click(screen.getByText('知识权限管理', { selector: '.nav-item' }))

    expect(window.location.search).toBe('?view=knowledge')
    await waitFor(() => expect(screen.getByRole('heading', { name: '知识权限管理' })).toBeInTheDocument())
  })

  it('falls back to the content workbench for an unknown view', async () => {
    window.history.replaceState({}, '', '/?view=unknown')

    render(<App />)

    await waitFor(() => expect(screen.getByRole('heading', { name: '内容工作台' })).toBeInTheDocument())
  })

  it('updates the rendered view when the browser history changes', async () => {
    render(<App />)

    window.history.pushState({}, '', '/?view=knowledge')
    window.dispatchEvent(new PopStateEvent('popstate'))
    await waitFor(() => expect(screen.getByRole('heading', { name: '知识权限管理' })).toBeInTheDocument())

    window.history.pushState({}, '', '/')
    window.dispatchEvent(new PopStateEvent('popstate'))
    await waitFor(() => expect(screen.getByRole('heading', { name: '内容工作台' })).toBeInTheDocument())
  })
})
