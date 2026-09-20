/**
 * 「知识检索」块：**范围由服务端解析**（客户端只选"以哪个岗位 / 哪个数字员工检索"，不带租户 / 知识库 id）。
 *
 * 三条口径（契约 §4，真机实测）：
 *  ① 请求体只有 `{query, role_key | agent_key, limit}`；
 *  ② **fail-closed**：白名单为空（未登记 / 未发布）时不请求上游，返回 `items=[] reason="empty_whitelist"`
 *     ⇒ 界面必须与「真的没查到」**分开呈现**，并给"先登记并发布"的指引；
 *  ③ 上游 fail-open 由服务端 `scoped_search` 收敛兜住 ⇒ 本块**只呈现服务端最终结果，不做二次裁剪**。
 * 未配置知识服务 ⇒ `503` ⇒ 呈现「服务未接入」（**不是空结果**）。
 */
import { useState } from 'react'
import { Alert, Button, Form, Input, List, Radio, Space, Typography } from 'antd'
import { tokens } from '../../../theme/tokens'
import {
  KnowledgeError,
  SEARCH_EMPTY_WHITELIST_NOTE,
  SEARCH_LIMIT,
  SEARCH_NO_BINDING_NOTE,
  SEARCH_NO_HITS_NOTE,
  SEARCH_NOT_CONFIGURED_NOTE,
  searchKnowledge,
} from '../services/knowledgeService'
import type { SearchOutcome } from '../types'

/** 空结果但服务端未给出归因时的中性文案（**不臆测**成"没查到"或"未发布"）。 */
export const SEARCH_UNATTRIBUTED_EMPTY_NOTE = '没有检索到内容。'

/**
 * 自限检索的说明（非管理角色）。
 *
 * 后端口径（`app/main.py` 的 `_ensure_search_scope_self_limited`）：非管理角色的 `role_key`
 * 必须等于**自身角色**，且不开放 `agent_key` 通道 —— 否则就能填任意岗位键读到别人的知识范围。
 * 界面据此**不提供身份选择**，如实说明"按你本人的角色范围检索"。
 */
export const SEARCH_SELF_SCOPED_NOTE = '检索范围按你本人的角色解析（服务端限定，不能代他人检索）。'

interface SearchFormValues {
  kind: 'role' | 'agent'
  key: string
  query: string
}

export interface SearchPanelProps {
  /**
   * 自限检索：给定后**不渲染**「以谁的身份检索」，一律按该角色检索（非管理角色传入自身角色）。
   * 管理角色（ceo / super_admin）不传 ⇒ 保留身份选择（治理台需要按岗位 / 数字员工核查检索效果）。
   */
  fixedRoleKey?: string
}

type SearchState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'not_configured' }
  | { kind: 'error'; message: string }
  | { kind: 'done'; outcome: SearchOutcome }

export function SearchPanel({ fixedRoleKey }: SearchPanelProps = {}) {
  const [form] = Form.useForm<SearchFormValues>()
  const [state, setState] = useState<SearchState>({ kind: 'idle' })
  const selfScoped = typeof fixedRoleKey === 'string' && fixedRoleKey.length > 0

  const handleSubmit = async () => {
    const values = form.getFieldsValue()
    const key = (values.key ?? '').trim()
    const query = (values.query ?? '').trim()
    setState({ kind: 'loading' })
    try {
      const outcome = await searchKnowledge({
        query,
        // 自限检索：只发送**本人角色**，不发 agent_key（后端对非管理角色关闭该通道）
        ...(selfScoped
          ? { role_key: fixedRoleKey }
          : values.kind === 'agent'
            ? { agent_key: key }
            : { role_key: key }),
        limit: SEARCH_LIMIT,
      })
      setState({ kind: 'done', outcome })
    } catch (error) {
      if (error instanceof KnowledgeError && error.kind === 'not_configured') {
        setState({ kind: 'not_configured' })
        return
      }
      setState({
        kind: 'error',
        message: error instanceof Error && error.message ? error.message : '检索未完成，请稍后重试。',
      })
    }
  }

  return (
    <div>
      <Typography.Title level={3}>知识检索</Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        {selfScoped
          ? SEARCH_SELF_SCOPED_NOTE
          : '按岗位或数字员工的可检索范围检索；范围由服务端解析，本页不选择知识库。'}
      </Typography.Paragraph>

      <Form<SearchFormValues>
        form={form}
        layout="inline"
        style={{ marginTop: tokens.spacing.sm, rowGap: tokens.spacing.sm }}
      >
        {!selfScoped && (
          <>
            <Form.Item name="kind" label="以谁的身份检索" initialValue="role">
              <Radio.Group>
                <Radio.Button value="role">岗位</Radio.Button>
                <Radio.Button value="agent">数字员工</Radio.Button>
              </Radio.Group>
            </Form.Item>
            <Form.Item
              name="key"
              label="身份标识"
              rules={[{ required: true, message: '请填写岗位或数字员工标识' }, { max: 64, message: '标识最长 64 个字符' }]}
            >
              <Input placeholder="岗位标识或数字员工标识" style={{ width: 200 }} autoComplete="off" />
            </Form.Item>
          </>
        )}
        <Form.Item
          name="query"
          label="检索关键词"
          rules={[{ required: true, message: '请填写检索关键词' }, { max: 500, message: '关键词最长 500 个字符' }]}
        >
          <Input placeholder="要检索的内容" style={{ width: 220 }} autoComplete="off" />
        </Form.Item>
        <Form.Item>
          <Button type="primary" loading={state.kind === 'loading'} onClick={() => void handleSubmit()}>
            检索
          </Button>
        </Form.Item>
      </Form>

      <div style={{ marginTop: tokens.spacing.md }}>
        {state.kind === 'not_configured' && (
          <Alert type="warning" showIcon message="服务未接入" description={SEARCH_NOT_CONFIGURED_NOTE} />
        )}
        {state.kind === 'error' && (
          <Alert type="error" showIcon message={`检索未完成：${state.message}`} />
        )}
        {state.kind === 'done' && <SearchResultView outcome={state.outcome} />}
      </div>
    </div>
  )
}

/** 结果呈现：空结果按**归因**分开说清楚；有结果时如实列出（含服务端截断提示）。 */
function SearchResultView({ outcome }: { outcome: SearchOutcome }) {
  if (outcome.items.length === 0) {
    if (outcome.reason === 'empty_whitelist') {
      return <Alert type="warning" showIcon message="暂无可检索文档" description={SEARCH_EMPTY_WHITELIST_NOTE} />
    }
    if (outcome.reason === 'no_binding') {
      return <Alert type="warning" showIcon message="检索范围为空" description={SEARCH_NO_BINDING_NOTE} />
    }
    if (outcome.reason === 'no_hits') {
      return <Alert type="info" showIcon message="没有匹配的内容" description={SEARCH_NO_HITS_NOTE} />
    }
    return <Alert type="info" showIcon message={SEARCH_UNATTRIBUTED_EMPTY_NOTE} />
  }

  return (
    <Space direction="vertical" size={tokens.spacing.sm} style={{ width: '100%' }}>
      <Typography.Text type="secondary">共 {outcome.items.length} 条引用。</Typography.Text>
      {outcome.truncated && (
        <Alert type="info" showIcon message="结果已按服务端上限截断展示。" />
      )}
      <List
        bordered
        dataSource={outcome.items}
        renderItem={(item) => (
          <List.Item key={item.citation_id}>
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              <Typography.Text strong>{item.source_title || item.knowledge_id}</Typography.Text>
              <Typography.Text>{item.content}</Typography.Text>
              <Typography.Text type="secondary">
                {item.score === null ? '相关度未提供' : `相关度 ${item.score}`}
              </Typography.Text>
            </Space>
          </List.Item>
        )}
      />
    </Space>
  )
}