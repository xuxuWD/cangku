/**
 * 当前身份（外壳底部与设置页「账号」共用同一份口径）。
 * 现状：开发态身份来自启动配置（`VITE_USER_ROLE` / `VITE_USER_ID`）；
 * 未知角色一律原样展示，不做猜测、不假装是管理员。
 */
const ROLE_LABELS: Record<string, string> = {
  super_admin: '超级管理员',
  ceo: 'CEO',
  department_lead: '部门负责人',
  employee: '员工',
  customer_admin: '客户管理员',
}

export function resolveIdentity(): { roleLabel: string; userId: string; role: string } {
  const role = import.meta.env.VITE_USER_ROLE || 'super_admin'
  return {
    role,
    roleLabel: ROLE_LABELS[role] ?? role,
    userId: import.meta.env.VITE_USER_ID || 'admin',
  }
}