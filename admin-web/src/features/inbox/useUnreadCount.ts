import { useCallback, useEffect, useState } from 'react'
import { listInbox } from './api'

// 收件箱发生变化（标记已读 / 全部已读）时广播，导航角标据此刷新。
export const INBOX_CHANGED_EVENT = 'workbench:inbox-changed'

// 侧边栏未读角标：进入应用时取一次，收到变更事件后再取一次；失败时静默保留上一次的值。
export function useUnreadCount(): number {
  const [count, setCount] = useState(0)

  const load = useCallback(async () => {
    try {
      const data = await listInbox(true, 1)
      setCount(typeof data.unread_count === 'number' ? data.unread_count : 0)
    } catch {
      // 角标是辅助信息，读取失败不影响主流程。
    }
  }, [])

  useEffect(() => {
    void load()
    const handleChange = () => { void load() }
    window.addEventListener(INBOX_CHANGED_EVENT, handleChange)
    return () => window.removeEventListener(INBOX_CHANGED_EVENT, handleChange)
  }, [load])

  return count
}
