/**
 * 状态标签：取值是**受控枚举**（语义色），外部不能传颜色值。
 *
 * 纪律：业务状态必须先映射到 `StatusTone`，不在调用处写颜色；
 * 数据非就绪（未配置 / 样本不足 / 未验证）或处于 loading / empty / error / forbidden 时，
 * **不使用语义色**，也不允许出现"成功"这类结论性文案。
 * 颜色一律走 AntD 预设色（`Tag` 的 `color` 预设名），因此没有颜色字面量。
 */
import type { ReactNode } from 'react'
import { Tag } from 'antd'
import type { DataPresence } from './dataPresence'
import { DATA_PRESENCE_LABEL } from './dataPresence'
import type { ContentStateKind } from './ContentState'

/** 受控语义色枚举。 */
export type StatusTone = 'success' | 'warning' | 'danger' | 'neutral' | 'info'

/** 语义色 → AntD 预设色名（唯一映射处，禁止绕过）。 */
const TONE_COLOR: Record<StatusTone, 'success' | 'warning' | 'error' | 'default' | 'processing'> = {
  success: 'success',
  warning: 'warning',
  danger: 'error',
  neutral: 'default',
  info: 'processing',
}

/** 非就绪四态 → 中性/语义色 + 固定文案。 */
const STATE_TONE: Record<ContentStateKind, StatusTone> = {
  loading: 'info',
  empty: 'neutral',
  error: 'danger',
  forbidden: 'warning',
}

const STATE_TEXT: Record<ContentStateKind, string> = {
  loading: '加载中',
  empty: '暂无',
  error: '加载失败',
  forbidden: '无权限',
}

export interface StatusTagProps {
  /** 语义色，默认 `neutral`。 */
  tone?: StatusTone
  /** 标签文案（处于四态或数据非就绪时会被固定文案替换）。 */
  children?: ReactNode
  /** 数据可用性：非 `ready` 时改用中性标签显示"未配置 / 样本不足 / 未验证"。 */
  presence?: DataPresence
  /** 数据态：非 `ready` 时改用固定文案，不使用调用方给的语义色。 */
  state?: ContentStateKind | 'ready'
}

export function StatusTag({ tone = 'neutral', children, presence = 'ready', state = 'ready' }: StatusTagProps) {
  if (state !== 'ready') {
    return <Tag color={TONE_COLOR[STATE_TONE[state]]}>{STATE_TEXT[state]}</Tag>
  }

  if (presence !== 'ready') {
    return <Tag color={TONE_COLOR.neutral}>{DATA_PRESENCE_LABEL[presence]}</Tag>
  }

  return <Tag color={TONE_COLOR[tone]}>{children}</Tag>
}