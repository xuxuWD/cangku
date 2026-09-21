/**
 * 审计记录详情抽屉（只读）：元数据 + `detail` 键值对。
 *
 * 纪律：
 *  - 记录**不可修改**（审计是追加型日志）⇒ 本抽屉只读，没有任何写入口；
 *  - `detail` **按键值对渲染**（值只做字符串化，**绝不当 HTML 注入**）；
 *  - 无明细时给"该记录没有明细"的如实文案，不显示空白区域。
 */
import { Form, Input, Typography } from 'antd'
import { FormDrawer } from '../../../components'
import { tokens } from '../../../theme/tokens'
import { formatDateTime } from '../../../utils/format'
import { detailEntries } from '../types'
import type { AuditRecord } from '../types'

/** 字段缺省时的如实文案（**不编造**）。 */
export const NOT_SET_TEXT = '未记录'

export interface AuditDetailDrawerProps {
  record: AuditRecord | null
  onClose: () => void
}

export function AuditDetailDrawer({ record, onClose }: AuditDetailDrawerProps) {
  const [form] = Form.useForm()
  const entries = detailEntries(record?.detail)

  return (
    <FormDrawer
      open={record !== null}
      title={record ? `审计记录详情：${record.action}` : '审计记录详情'}
      form={form}
      readOnly
      onClose={onClose}
      onSubmit={() => undefined}
      width={640}
    >
      {record && (
        <>
          <Form.Item label="记录编号">
            <Input value={record.record_id} readOnly />
          </Form.Item>
          <Form.Item label="动作">
            <Input value={record.action} readOnly />
          </Form.Item>
          <Form.Item label="操作人">
            <Input value={record.actor_id ?? NOT_SET_TEXT} readOnly />
          </Form.Item>
          <Form.Item label="目标类型">
            <Input value={record.target_type ?? NOT_SET_TEXT} readOnly />
          </Form.Item>
          <Form.Item label="目标标识">
            <Input value={record.target_id ?? NOT_SET_TEXT} readOnly />
          </Form.Item>
          <Form.Item label="手机号（已脱敏）">
            <Input value={record.phone_masked ?? NOT_SET_TEXT} readOnly />
          </Form.Item>
          <Form.Item label="发生时间">
            <Input value={record.occurred_at ? formatDateTime(record.occurred_at) : NOT_SET_TEXT} readOnly />
          </Form.Item>

          <Typography.Title level={5} style={{ marginBottom: tokens.spacing.sm }}>
            明细
          </Typography.Title>
          {entries.length === 0 ? (
            <Typography.Text type="secondary">该记录没有明细。</Typography.Text>
          ) : (
            entries.map((entry) => (
              <Form.Item key={entry.key} label={entry.key}>
                <Input value={entry.value} readOnly />
              </Form.Item>
            ))
          )}
        </>
      )}
    </FormDrawer>
  )
}