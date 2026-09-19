import type { ApiErrorShape } from '../inbox/types'
import type { PendingApprovalList } from './types'

const apiBase = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1').replace(/\/$/, '')

function headers(extra: HeadersInit = {}): HeadersInit {
  return { Accept: 'application/json', 'Content-Type': 'application/json', 'X-Tenant-Id': import.meta.env.VITE_TENANT_ID || 'demo-tenant', 'X-User-Id': import.meta.env.VITE_USER_ID || 'admin', 'X-User-Role': import.meta.env.VITE_USER_ROLE || 'super_admin', ...extra }
}

// 只取服务端自己写的中文 detail（字符串）；数组形式的参数校验错误一律丢弃。
async function detailFrom(response: Response): Promise<string | null> {
  try {
    const body = await response.json() as { detail?: unknown }
    return typeof body.detail === 'string' && body.detail.trim() ? body.detail.trim() : null
  } catch {
    return null
  }
}

/**
 * 「待我审批」聚合（只读）。
 * 非审批角色由服务端返回 **200 + 空列表 + 全 0 计数**（便于直接展示「暂无待办」），
 * 因此这里不把「空」当异常；401/403 才按无权限提示。
 */
export async function listPendingApprovals(limit = 50): Promise<PendingApprovalList> {
  let response: Response
  try {
    response = await fetch(`${apiBase}/approvals/pending?limit=${limit}`, { headers: headers() })
  } catch {
    throw { status: 0, message: '待办服务暂时不可用，请检查网络后重新尝试。', retryable: true, unauthorized: false } satisfies ApiErrorShape
  }
  if (!response.ok) {
    const unauthorized = response.status === 401 || response.status === 403
    const detail = await detailFrom(response)
    throw {
      status: response.status,
      message: unauthorized ? (detail || '当前账号没有查看待办审批的权限。') : (detail || `服务暂时无法完成请求（${response.status}）。`),
      retryable: !unauthorized && response.status >= 500,
      unauthorized,
    } satisfies ApiErrorShape
  }
  return await response.json() as PendingApprovalList
}