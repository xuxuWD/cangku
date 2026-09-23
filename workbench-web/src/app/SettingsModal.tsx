/**
 * 设置弹窗（B3 §7 第 1 步 + 验收 A8）
 *
 * 规格 §7 逐字：「**配置类收进设置弹窗**（人员/权限/审计/用量/模型/渠道…）」。
 * 验收 **A8**：「**管理类功能全部可从设置弹窗到达**」。
 *
 * ⚠️ **收敛必须是可逆的**（规格 §13.2 R5）：这里收进来的都是**仅管理员可见**的入口
 * （接口契约限定的角色，见 `navigation.ts` 的 `ADMIN_ONLY` / `BILLING_ROLES`），
 * **页面本身一行没改、一条没删**，只是换了个到达方式。所以「我的功能不见了」这个疑虑不成立 ——
 * 至少对这四个角色之外的人来说，**他们本来也看不到这几项**。
 *
 * ⚠️ **为什么只收这三项**：B3 §10 明写"哪块放哪"依赖 B1 §4.2 的逐模块归属表**（待你勾选）**，
 * 「本文不重复」。所以这里**只做不依赖那张表的收敛**：把**管理类**收掉即可达到 §2 的目标结构，
 * 而**不动任何 B1 §4.2 还没裁的归属**（如知识库 / 审计到底进不进设置）。
 */
import { Modal, Space, Table, Tag, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { ADMIN_SETTINGS_ENTRIES } from './navigation'
import type { AdminSettingsEntry } from './navigation'
import { navigateShell, shellRoute } from './shellRouter'

const HOW_COLOR: Record<AdminSettingsEntry['how'], string> = {
  配置类收进设置: 'blue',
  同类合并: 'purple',
}

export function SettingsModal({
  open,
  onClose,
  visibleKeys,
}: {
  open: boolean
  onClose: () => void
  /** 当前角色**确实可见**的管理项键（角色不可见的不列 —— 不摆点了必 403 的假入口）。 */
  visibleKeys: readonly string[]
}) {
  const rows = ADMIN_SETTINGS_ENTRIES.filter((entry) => visibleKeys.includes(entry.key))

  const columns: TableColumnsType<AdminSettingsEntry> = [
    { title: '设置项', dataIndex: 'title', key: 'title' },
    { title: '原本在哪', dataIndex: 'from', key: 'from' },
    {
      title: '收敛方式',
      dataIndex: 'how',
      key: 'how',
      width: 160,
      render: (value: AdminSettingsEntry['how']) => <Tag color={HOW_COLOR[value]}>{value}</Tag>,
    },
    {
      title: '操作',
      key: 'action',
      width: 90,
      render: (_value, entry) => (
        <Typography.Link
          // 表格里每行都有一个「打开」⇒ 必须给出**可区分的可及名**，否则读屏与用例都分不清是哪一行
          aria-label={`打开${entry.title}`}
          onClick={() => {
            navigateShell(shellRoute(entry.key))
            onClose()
          }}
        >
          打开
        </Typography.Link>
      ),
    },
  ]

  return (
    <Modal
      title="设置"
      open={open}
      onCancel={onClose}
      footer={null}
      width={880}
      destroyOnHidden
    >
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Typography.Text type="secondary">
          管理类功能**不是被删掉，是被收进这里**（B3 §7）。下表列出每一项原本在哪、用哪一招收的；
          点「打开」即进入该页 —— URL 随之变化，可直接分享。
        </Typography.Text>
        <Table<AdminSettingsEntry>
          columns={columns}
          dataSource={rows}
          rowKey={(row) => row.key}
          pagination={false}
          size="small"
          locale={{ emptyText: '当前角色没有可到达的管理项。' }}
        />
        {visibleKeys.length === 0 && (
          <Typography.Text type="secondary">
            这与你的岗位有关：管理类入口只对广告里的管理员角色开放，界面不摆点了必被拒绝的入口。
          </Typography.Text>
        )}
      </Space>
    </Modal>
  )
}
