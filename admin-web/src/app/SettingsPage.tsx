import { useState } from 'react'
import { Icon } from '../components/Icon'
import { Segmented } from '../components/ui/Segmented'
import { GUIDES, SHORTCUTS, START_PATHS } from './guides'
import { resolveIdentity } from './identity'
import { THEME_LABELS, THEME_MODES } from './theme'
import { useTheme } from './ThemeProvider'

type SettingsGroup = 'appearance' | 'help' | 'account'

const GROUPS: Array<{ value: SettingsGroup; label: string }> = [
  { value: 'appearance', label: '外观' },
  { value: 'help', label: '帮助与反馈' },
  { value: 'account', label: '账号' },
]

/**
 * 设置（UI v2 §3.2 新增全屏页）：外观 / 帮助与反馈 / 账号。
 * **不新增功能**——把原来散在外壳上的主题切换与帮助入口换到该有的位置。
 */
export function SettingsPage() {
  const [group, setGroup] = useState<SettingsGroup>('appearance')
  const theme = useTheme()
  const identity = resolveIdentity()

  return (
    <main className="settings">
      <nav className="settings__nav" aria-label="设置分组">
        {GROUPS.map((item) => (
          <button
            key={item.value}
            type="button"
            className={group === item.value ? 'is-active' : ''}
            aria-current={group === item.value ? 'true' : undefined}
            onClick={() => setGroup(item.value)}
          >
            {item.label}
          </button>
        ))}
      </nav>

      <div className="settings__content">
        {group === 'appearance' && (
          <>
            <section className="settings__card" aria-label="外观">
              <div className="settings__row">
                <span className="settings__row-main">
                  <strong>外观</strong>
                  <span>「跟随系统」会随操作系统的深浅色自动切换。</span>
                </span>
                <Segmented
                  label="外观"
                  value={theme.mode}
                  options={THEME_MODES.map((mode) => ({ value: mode, label: THEME_LABELS[mode] }))}
                  onChange={theme.setMode}
                />
              </div>
              <p className="settings__hint">
                当前生效：{theme.resolved === 'dark' ? '深色' : '浅色'}。左栏底部的月亮 / 太阳按钮可一键切换浅色与深色。
              </p>
            </section>
          </>
        )}

        {group === 'help' && (
          <>
            <section className="settings__card" aria-label="怎么开始">
              <div className="card__head">
                <h2>怎么开始</h2>
              </div>
              <div className="rows">
                {START_PATHS.map((path) => (
                  <div className="row" key={path.label}>
                    <span className="avatar" aria-hidden="true">智</span>
                    <span className="row__main">
                      <span className="row__title">{path.label}</span>
                      <span className="row__sub">{path.hint}</span>
                    </span>
                  </div>
                ))}
              </div>
            </section>

            <section className="settings__card" aria-label="快捷键">
              <div className="card__head">
                <h2>快捷键</h2>
              </div>
              <div className="rows">
                {SHORTCUTS.map((item) => (
                  <div className="row" key={item.keys}>
                    <span className="row__main">
                      <span className="row__title"><span className="kbd">{item.keys}</span></span>
                      <span className="row__sub">{item.what}</span>
                    </span>
                  </div>
                ))}
              </div>
            </section>

            <section className="settings__card" aria-label="每页的使用指南">
              <div className="card__head">
                <h2>每页的使用指南</h2>
              </div>
              <p className="settings__hint">
                每个页面右上角都有「使用指南」（快捷键 <span className="kbd">?</span>），
                打开的是那一页的说明。以下是各页指南的标题，方便你按页面找：
              </p>
              <p className="settings__hint">
                {Object.values(GUIDES).map((guide) => guide.title).join(' · ')}
              </p>
            </section>

            <section className="settings__card" aria-label="版本">
              <div className="card__head">
                <h2>关于</h2>
              </div>
              <div className="settings__row">
                <span className="settings__row-main">
                  <strong>版本 {__APP_VERSION__}</strong>
                  <span>反馈问题时请带上这个版本号，方便我们定位。</span>
                </span>
                <Icon name="help" size={16} />
              </div>
            </section>
          </>
        )}

        {group === 'account' && (
          <section className="settings__card" aria-label="账号">
            <div className="settings__row">
              <span className="avatar" aria-hidden="true">{identity.roleLabel.slice(0, 1)}</span>
              <span className="settings__row-main">
                <strong>{identity.roleLabel}</strong>
                <span>账号 {identity.userId}</span>
              </span>
            </div>
            <p className="settings__hint">
              当前展示的是本机启动配置里的身份；接入登录后，这里会显示你的真实账号与角色。权限由服务端判定，界面上看不到不等于不能做。
            </p>
          </section>
        )}
      </div>
    </main>
  )
}