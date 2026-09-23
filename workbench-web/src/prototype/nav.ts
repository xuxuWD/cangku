/**
 * B3 原型 · 侧栏定义（**侧栏收敛**，规格 §2 + §7 + 验收 A1）
 *
 * 规格原话（`2026-09-22-information-architecture-design.md` §2）：
 * ```
 * ➕ 新建对话   ☑ 待我处理   🤖 我的数字员工   📋 工作项   📚 知识库
 * ▾ 更多：🕐 自动化  📁 文件  🧩 扩展
 * ────────────────────────────
 * ⚙ 设置（弹窗）   🔔 通知   👤 账号
 * ```
 * **目标：入口数 ≤ 10**（现 `admin-web` 17 + `workbench-web` 9 全平级）。
 *
 * ⚠️ **收敛必须是可逆的**（规格 §13.2 R5）：被收掉的入口**进设置弹窗、不是删除**，
 * 且验收 A8 要求「管理类功能全部可从设置弹窗到达」。本文件的 `SETTINGS_ENTRIES`
 * 就是这张"去了哪"的对照表 —— **不是丢弃清单**。
 */
import type { ComponentType } from 'react'
import {
  AppstoreOutlined,
  AuditOutlined,
  BookOutlined,
  ClockCircleOutlined,
  FileOutlined,
  FolderOpenOutlined,
  PlusOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  TeamOutlined,
  WalletOutlined,
} from '@ant-design/icons'

/** 主区域视图键（同时是 URL 的 `?view=` 取值，见 `router.ts`）。 */
export type PrototypeView =
  | 'chat'
  | 'todo'
  | 'agents'
  | 'workitems'
  | 'knowledge'
  | 'automation'
  | 'files'
  | 'extensions'

export interface NavEntry {
  view: PrototypeView
  title: string
  icon: ComponentType
}

/** 5 个主入口（规格 §2 侧栏结构的第一行）。 */
export const PRIMARY_NAV: readonly NavEntry[] = [
  { view: 'chat', title: '新建对话', icon: PlusOutlined },
  { view: 'todo', title: '待我处理', icon: AppstoreOutlined },
  { view: 'agents', title: '我的数字员工', icon: RobotOutlined },
  { view: 'workitems', title: '工作项', icon: FolderOpenOutlined },
  { view: 'knowledge', title: '知识库', icon: BookOutlined },
]

/** 「更多」子项（规格 §2 第二行，≤4 项）。 */
export const MORE_NAV: readonly NavEntry[] = [
  { view: 'automation', title: '自动化', icon: ClockCircleOutlined },
  { view: 'files', title: '文件', icon: FileOutlined },
  { view: 'extensions', title: '扩展', icon: AppstoreOutlined },
]

/**
 * **设置弹窗**里收纳的入口（规格 §2「管理类收进设置弹窗」逐字）：
 * 人员与岗位 · 知识权限 · 审计 · 用量与费用 · 模型 · 渠道 · 数据与资源。
 *
 * `from` 列写明它**原本在哪** —— 这是"可逆收敛"的证据：每一项都能指出它的来源。
 */
export interface SettingsEntry {
  key: string
  title: string
  icon: ComponentType
  from: string
  /** 收敛方式（规格 §7 的四步路径）。 */
  how: '配置类收进设置' | '同类合并' | '下钻代替入口' | '归档开发期页面'
}

export const SETTINGS_ENTRIES: readonly SettingsEntry[] = [
  { key: 'workforce', title: '人员与岗位', icon: TeamOutlined, from: 'admin-web `workforce` + `workforceSettings`', how: '配置类收进设置' },
  { key: 'knowledge-access', title: '知识权限', icon: SafetyCertificateOutlined, from: 'admin-web `knowledgeAccess` + workbench-web `permissions`', how: '配置类收进设置' },
  { key: 'audit', title: '审计', icon: AuditOutlined, from: 'workbench-web `audit-log`', how: '配置类收进设置' },
  { key: 'billing', title: '用量与费用', icon: WalletOutlined, from: '（本原型之前已合并进基座）', how: '配置类收进设置' },
  { key: 'skills', title: '扩展能力（Skill & MCP）', icon: AppstoreOutlined, from: 'workbench-web `skills-mcp`', how: '配置类收进设置' },
  { key: 'model', title: '模型', icon: SettingOutlined, from: 'admin-web `workforceSettings` 内的模型候选', how: '配置类收进设置' },
  { key: 'crm', title: '客户（CRM 五视图）', icon: FolderOpenOutlined, from: 'admin-web `crm×5`', how: '同类合并' },
  { key: 'playground', title: '组件样品（开发期）', icon: AppstoreOutlined, from: 'workbench-web `components-playground`', how: '归档开发期页面' },
]

/** 顶栏右侧三项（不属于「≤10 入口」的业务导航计数，规格 §2 第三行）。 */
export interface TopAction {
  key: 'settings' | 'notification' | 'account'
  title: string
}

export const TOP_ACTIONS: readonly TopAction[] = [
  { key: 'settings', title: '设置' },
  { key: 'notification', title: '通知' },
  { key: 'account', title: '账号' },
]

/**
 * 侧栏业务入口计数（验收 A1 的口径）。
 *
 * 口径：**主入口 5 + 更多 3 = 8**；「设置 / 通知 / 账号」是顶栏动作（其中"设置"开弹窗），
 * **不计入侧栏入口数**。8 + 设置弹窗 1 = 9 ≤ 10 ✓
 */
export const SIDEBAR_ENTRY_COUNT = PRIMARY_NAV.length + MORE_NAV.length

export function findNav(view: PrototypeView): NavEntry | undefined {
  return [...PRIMARY_NAV, ...MORE_NAV].find((item) => item.view === view)
}
