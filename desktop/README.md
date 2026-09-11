# 公司数字员工工作台 Windows 桌面端

主员工端采用 Windows 桌面端。本工程是 **Electron 安全壳**：只负责提供一个受约束的
浏览器容器并加载网页端界面，业务逻辑全部通过版本化服务端 API 完成，客户端不直连数据库。

> 本目录目前只是**壳工程 + 安全配置 + 打包配置 + 测试**。不含自动更新能力。

## 两种加载模式

| 模式 | 触发条件 | 说明 |
|------|----------|------|
| 远程模式 | 设置了 `WORKBENCH_DESKTOP_URL` | 加载已部署的网页端或本地开发服务器（默认 `http://localhost:5173/`） |
| 内置模式 | 未设置 `WORKBENCH_DESKTOP_URL`，且 `desktop/web/index.html` 存在 | 用 `file://` 加载随包分发的 `admin-web` 构建产物 |

内置产物由 `npm run copy:web` 生成（把 `admin-web/dist` 复制到 `desktop/web`）。

## 环境变量

- `WORKBENCH_DESKTOP_URL`：远程模式的目标地址；留空则走内置模式或默认开发地址。
- `WORKBENCH_DESKTOP_ALLOWED_ORIGINS`：允许加载与导航的来源白名单，英文逗号分隔；
  留空时使用默认值 `http://localhost:5173`、`http://127.0.0.1:5173`。

## 命令

```powershell
npm test          # 零依赖单元测试（Node 内置 node:test，无需 npm install）
npm run copy:web  # 复制 admin-web/dist 到 desktop/web
npm start         # 启动桌面端（需要已安装 electron）
npm run pack      # 生成未打包目录（需要已安装 electron-builder）
npm run dist      # 生成 Windows NSIS 安装包（需要已安装 electron-builder）
```

> `npm test` 只依赖 Node 内置模块，**不需要 `npm install`**，因此可在没有任何
> Node 依赖、也无法运行 GUI 的机器上执行。

## 安全约定

- `contextIsolation: true` + `nodeIntegration: false` + `sandbox: true`：渲染进程拿不到 Node 能力。
- `webSecurity: true` 且 `allowRunningInsecureContent: false`：不做任何降低浏览器安全策略的放行。
- 外链交给系统浏览器打开（`setWindowOpenHandler` 返回 `deny`），不在应用内新开窗口。
- 导航白名单：`will-navigate` 只放行白名单 origin，其余一律 `preventDefault`。
- 禁止 webview 挂载（`will-attach-webview` 直接 `preventDefault`）。
- 预加载脚本只透出一个只读对象，绝不暴露 `ipcRenderer`、`fs`、`child_process` 等能力。
- 单实例锁：重复启动只聚焦已有窗口。

## 已知限制（未验收项）

- **内置模式的导航取舍**：`isAllowedNavigation` 按设计拒绝 `file:` 协议（`file://` 的 origin 为 `null`，放行它等于放行任意本地文件）。因此内置模式下应用内必须使用 SPA 前端路由（`history.pushState`），不能做整页跳转；这是刻意的 fail-closed 取舍。
- **远程模式的跨源限制**：网页端与后端跨源时需要后端 CORS 放行 `Authorization` 头（当前仅 development 环境开放 CORS 且未含该头），**真实跨源部署属未验收项**。
- **依赖已固定**：`electron 44.3.0`、`electron-builder 26.15.3`（精确版本，非 `latest`），并已提交 `package-lock.json` 锁定整棵依赖树。
  本机安装使用 `npm install --ignore-scripts`，**有意跳过 Electron 二进制下载**（`postinstall` 被跳过），因此 `node --test` 可零网络依赖运行，但 `npm start` / `npm run pack` / `npm run dist` 在本机仍无法执行。
- 未做代码签名与公证，安装包在 Windows 上可能触发 SmartScreen 警告。
- 未实现自动更新（本工程不引入 `electron-updater`，也没有任何自动更新相关代码）。
- 开发机没有 Electron 运行时、没有签名证书：**真实安装包构建、代码签名、公证、
  以及宪法 2.5 要求的干净电脑安装测试，均为未验收项**，尚未执行。
