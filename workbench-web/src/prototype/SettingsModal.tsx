/**
 * B3 原型 · 设置弹窗（规格 §7 第 1 步 + 验收 A8）
 *
 * 规格 §7 逐字：「**配置类收进设置弹窗**（人员/权限/审计/用量/模型/渠道…）——EvoFlow 用这一招收掉了 13 个 Tab」。
 * 验收 **A8**：「**管理类功能全部可从设置弹窗到达**」。
 *
 * ⚠️ **这是"可逆收敛"的落点**（规格 §13.2 R5）：被收掉的入口**在这里仍可到达**，
 * 且每一项都标了**它原本在哪**（`SETTINGS_ENTRIES.from`）与**用的哪一招**（`.how`）。
 * 这样"我的功能不见了"的疑虑可以用一张表回答，而不是靠记忆。
 */
import { Alert, Modal, Table, Tag, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { SETTINGS_ENTRIES } from './nav'
import type { SettingsEntry } from './nav'

const HOW_COLOR: Record<SettingsEntry['how'], string> = {
  配置类收进设置: 'blue',
  同类合并: 'purple',
  下钻代替入口: 'cyan',
  归档开发期页面: 'default',
}

export function SettingsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const columns: TableColumnsType<SettingsEntry> = [
    {
      title: '设置项',
      dataIndex: 'title',
      key: 'title',
      render: (value: string, item) => (
        <Typography.Text>
          <item.icon /> {value}
        </Typography.Text>
      ),
    },
    { title: '原本在哪', dataIndex: 'from', key: 'from' },
    {
      title: '收敛方式',
      dataIndex: 'how',
      key: 'how',
      width: 160,
      render: (value: SettingsEntry['how']) => <Tag color={HOW_COLOR[value]}>{value}</Tag>,
    },
  ]

  return (
    <Modal
      title="设置"
      open={open}
      onCancel={onClose}
      footer={null}
      width={860}
      // 内容按需重建即可 —— 这里没有"不能卸载"的要求（那条只针对对话与悬浮助手）
      destroyOnHidden
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="管理类功能不是被删掉，是被收进这里"
        description="收敛必须可逆（B3 §13.2 R5）：下表列出每一项**原本在哪**、用哪一招收的，保证「仍可到达」。"
      />
      <Table<SettingsEntry> columns={columns} dataSource={[...SETTINGS_ENTRIES]} rowKey={(row) => row.key} pagination={false} size="small" />
    </Modal>
  )
}
