import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PermissionGuard } from './PermissionGuard'
import { useSession } from '../app/session'

describe('PermissionGuard', () => {
  beforeEach(() => {
    useSession.setState({ role: 'employee' })
  })

  it('有权限：渲染 children，不出现无权限态', () => {
    useSession.setState({ role: 'super_admin' })
    render(
      <PermissionGuard capability="agent.manage">
        <div>仅管理员可见的内容</div>
      </PermissionGuard>,
    )
    expect(screen.getByText('仅管理员可见的内容')).toBeInTheDocument()
    expect(screen.queryByText('无访问权限')).not.toBeInTheDocument()
  })

  it('无权限：**渲染"无权限"态而不是静默隐藏** —— 有原因、有申请入口、且不渲染 children', async () => {
    let requested = 0
    render(
      <PermissionGuard capability="agent.manage" onRequestAccess={() => { requested += 1 }}>
        <div>仅管理员可见的内容</div>
      </PermissionGuard>,
    )
    expect(screen.getByText('无访问权限')).toBeInTheDocument()
    expect(screen.getByText(/没有「数字员工管理」权限/)).toBeInTheDocument()
    expect(screen.queryByText('仅管理员可见的内容')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '申请权限' }))
    expect(requested).toBe(1)
  })

  it('四态口径：无权限态可用自定义原因覆盖', () => {
    render(
      <PermissionGuard capability="data.delete" reason="删除操作仅限管理员。">
        <div>删除区</div>
      </PermissionGuard>,
    )
    expect(screen.getByText('删除操作仅限管理员。')).toBeInTheDocument()
  })

  it('角色切换后按新角色重新判定', async () => {
    render(
      <PermissionGuard capability="agent.manage">
        <div>仅管理员可见的内容</div>
      </PermissionGuard>,
    )
    expect(screen.queryByText('仅管理员可见的内容')).not.toBeInTheDocument()

    act(() => {
      useSession.setState({ role: 'super_admin' })
    })
    expect(screen.getByText('仅管理员可见的内容')).toBeInTheDocument()
  })
})