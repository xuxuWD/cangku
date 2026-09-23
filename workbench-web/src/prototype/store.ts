/**
 * B3 原型 · 单一状态树
 *
 * 规格 §4 要求 ④ 逐字：**「侧栏的『最近会话列表』与对话同一个状态树」**
 * （否则两处状态不同步）。本文件就是那棵树：侧栏的最近会话、主区域的对话、
 * 右栏要用的当前对象**都从这里读**，不各持一份 useState。
 *
 * **本原型不接后端**（用户要求"不动后端"）：消息与「待你处理」均为样例数据，
 * 但**机制是真的** —— 后台产出用一个真 `setInterval` 模拟，用来证明
 * 「对话切走只隐藏、不卸载」（验收 A2 / A3 的可观测证据）。
 */
import { create } from 'zustand'
// 排序口径从**唯一实现**处取（`src/app/assistantRules.ts`），本文件不再自己定义一份
import { ATTENTION_ORDER } from '../app/assistantRules'
import type { AttentionKind } from '../app/assistantRules'

export interface ConversationSummary {
  id: string
  title: string
  updatedAt: string
  unread: number
}

export interface ChatMessage {
  id: string
  role: 'user' | 'employee' | 'system'
  /** 语义化步骤（规格 §9 手法 2：把工具调用折叠成中文步骤条，而不是裸日志）。 */
  step?: { label: string; state: 'done' | 'running' | 'failed' }
  text: string
  at: string
}

/** 「待你处理」条目（规格 §6：数据源本就是 `app/inbox.py`；此处为样例）。 */
export interface AttentionItem {
  id: string
  title: string
  /** 排序权重：待审批 > 待输入 > 受阻 > 失败 > 完成（规格 §6 逐字顺序）。 */
  kind: AttentionKind
  objectId: string
}

const SAMPLE_CONVERSATIONS: readonly ConversationSummary[] = [
  { id: 'conv-1', title: 'Q3 内容排期', updatedAt: '2026-09-23T02:10:00Z', unread: 2 },
  { id: 'conv-2', title: '竞品资料抓取', updatedAt: '2026-09-22T09:40:00Z', unread: 0 },
  { id: 'conv-3', title: '新客户 onboarding', updatedAt: '2026-09-21T14:05:00Z', unread: 0 },
]

const SAMPLE_MESSAGES: readonly ChatMessage[] = [
  { id: 'm1', role: 'user', text: '把「Q3 内容排期」这周的三篇稿子排出来。', at: '02:10' },
  {
    id: 'm2',
    role: 'employee',
    step: { label: '读取知识库「内容规范 v3」', state: 'done' },
    text: '好的，先核对规范。',
    at: '02:10',
  },
  {
    id: 'm3',
    role: 'employee',
    step: { label: '生成三篇选题与草稿', state: 'done' },
    text: '三篇草稿已生成，标题与摘要如下 —— 需要你确认后我再提交审批。',
    at: '02:12',
  },
]

export const SAMPLE_ATTENTION: readonly AttentionItem[] = [
  { id: 'a1', title: '任务「Q3 内容排期」等待你审批', kind: '待审批', objectId: 'task-1' },
  { id: 'a2', title: '工作项「竞品资料抓取」需要补充抓取范围', kind: '待输入', objectId: 'task-2' },
  { id: 'a3', title: '运行「月度报表」因缺少数据源受阻', kind: '受阻', objectId: 'run-1' },
  { id: 'a4', title: '运行「客户回访」失败', kind: '失败', objectId: 'run-2' },
  { id: 'a5', title: '任务「新客户 onboarding」已完成', kind: '完成', objectId: 'task-3' },
]

/** 右栏当前对象的样例详情（规格 §5：只放「当前对象的简要信息 + 数字员工面板」）。 */
export interface ObjectBrief {
  id: string
  title: string
  kind: string
  status: string
  /** 上下文注入字段名（规格 §5 的 `agentIntegration.contextFields` 设计）。 */
  contextField: string
}

export const OBJECT_BRIEFS: Record<string, ObjectBrief> = {
  'task-1': { id: 'task-1', title: 'Q3 内容排期', kind: '任务', status: '等待审批', contextField: 'current_task_id' },
  'task-2': { id: 'task-2', title: '竞品资料抓取', kind: '任务', status: '待补充输入', contextField: 'current_task_id' },
  'run-1': { id: 'run-1', title: '月度报表', kind: '运行', status: '受阻', contextField: 'current_run_id' },
  'run-2': { id: 'run-2', title: '客户回访', kind: '运行', status: '失败', contextField: 'current_run_id' },
  'task-3': { id: 'task-3', title: '新客户 onboarding', kind: '任务', status: '已完成', contextField: 'current_task_id' },
}

interface PrototypeState {
  /* ---- 会话（侧栏"最近会话"与主区域对话共用这一份） ---- */
  conversations: ConversationSummary[]
  activeConversationId: string
  messages: ChatMessage[]
  setActiveConversation: (id: string) => void
  appendMessage: (message: ChatMessage) => void

  /* ---- 「切走不卸载」的可观测证据：后台产出计数 ---- */
  backgroundRunning: boolean
  backgroundTicks: number
  toggleBackground: () => void
  bumpBackground: () => void

  /* ---- 悬浮助手 ---- */
  assistantOpen: boolean
  setAssistantOpen: (open: boolean) => void
  /** 悬浮助手里输入的最后一句（纯规则意图路由用，**不调 LLM**，规格 §11 N3）。 */
  assistantDraft: string
  setAssistantDraft: (text: string) => void

  /* ---- 设置弹窗 ---- */
  settingsOpen: boolean
  setSettingsOpen: (open: boolean) => void
}

export const usePrototypeStore = create<PrototypeState>()((set) => ({
  conversations: [...SAMPLE_CONVERSATIONS],
  activeConversationId: SAMPLE_CONVERSATIONS[0].id,
  messages: [...SAMPLE_MESSAGES],
  setActiveConversation: (id) => set({ activeConversationId: id }),
  appendMessage: (message) => set((state) => ({ messages: [...state.messages, message] })),

  backgroundRunning: false,
  backgroundTicks: 0,
  toggleBackground: () => set((state) => ({ backgroundRunning: !state.backgroundRunning })),
  bumpBackground: () =>
    set((state) => ({
      backgroundTicks: state.backgroundTicks + 1,
      messages: [
        ...state.messages,
        {
          id: `bg-${state.backgroundTicks + 1}`,
          role: 'employee',
          step: { label: `后台第 ${state.backgroundTicks + 1} 拍产出（切走也不会停）`, state: 'done' },
          text: '这条消息由"后台产出"模拟器追加。',
          at: '—',
        },
      ],
    })),

  assistantOpen: false,
  setAssistantOpen: (open) => set({ assistantOpen: open }),
  assistantDraft: '',
  setAssistantDraft: (text) => set({ assistantDraft: text }),

  settingsOpen: false,
  setSettingsOpen: (open) => set({ settingsOpen: open }),
}))

export const SAMPLE_ATTENTION_SORTED: readonly AttentionItem[] = [...SAMPLE_ATTENTION].sort(
  (a, b) => ATTENTION_ORDER.indexOf(a.kind) - ATTENTION_ORDER.indexOf(b.kind),
)

/**
 * 重置为初始态（**仅供用例**）。
 *
 * 为什么需要：store 是**模块级**单例，用例之间会互相污染（上一条用例开着的抽屉、
 * 追加过的消息会漏给下一条）。测试里用 `beforeEach` 调它，保证每条用例从同一初始态起跑。
 */
export function resetPrototypeStore(): void {
  usePrototypeStore.setState({
    conversations: [...SAMPLE_CONVERSATIONS],
    activeConversationId: SAMPLE_CONVERSATIONS[0].id,
    messages: [...SAMPLE_MESSAGES],
    backgroundRunning: false,
    backgroundTicks: 0,
    assistantOpen: false,
    assistantDraft: '',
    settingsOpen: false,
  })
}
