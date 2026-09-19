# THIRD-PARTY-NOTICES

> **本文件由脚本生成，请勿手工编辑**：`py scripts/generate_third_party_notices.py`。
> 口径依据：宪法 12.3（第三方库逐个核对许可证；素材授权可追溯）与交付口径「每次升级都要重新生成 SBOM、扫描漏洞、核对许可证」。

## 1. 覆盖范围与证据来源

本清单覆盖以下**随交付物分发**的第三方组件，逐类写明证据来源（口径 = 锁文件 / 安装树全量，**不是**凭印象，也**不声称**等于最终镜像内的精确集合）：

| 产物 | 证据来源 | 口径 |
|---|---|---|
| 应用镜像（app / worker / beat 共用） | `requirements.lock`（`--require-hashes` 钉死）+ 各包 `dist-info/METADATA` | 锁文件全量 |
| 执行镜像（dsh 沙箱） | Linux `npm ci` 安装树（dsh 执行镜像依赖） | 安装树全量（含 optional 平台包） |
| 管理台 / 伴侣端 / 桌面端 | 各自 `package-lock.json` 的 `packages` 条目 | lockfile 全量（**含 devDependencies**，保守从宽） |

> **保守从宽**：npm 清单按 lockfile / 安装树全量列出（含开发依赖与平台可选包）——多列不构成违规，**漏列才构成**；因此本清单**不**声称「等于最终镜像内的精确集合」。

## 2. 许可证分布（按归一后的声明值）

| 许可证 | 组件数 |
|---|---|
| MIT | 854 |
| Apache-2.0 | 118 |
| ISC | 54 |
| BSD-3-Clause | 39 |
| MPL-2.0 | 24 |
| BSD-2-Clause | 13 |
| BlueOak-1.0.0 | 10 |
| MIT License | 8 |
| BSD License | 6 |
| MIT-0 | 5 |
| 0BSD | 2 |
| Apache Software License | 2 |
| CC0-1.0 | 2 |
| LGPL-3.0-only | 2 |
| Python-2.0 | 2 |
| (MIT OR CC0-1.0) | 1 |
| (WTFPL OR MIT) | 1 |
| Apache-2.0 AND LGPL-3.0-or-later AND MIT | 1 |
| Apache-2.0 OR BSD-2-Clause | 1 |
| Apache-2.0 OR BSD-3-Clause | 1 |
| LGPL-3.0-or-later | 1 |
| Mozilla Public License 2.0 (MPL 2.0) | 1 |
| PSF-2.0 | 1 |
| Unlicense | 1 |
| WTFPL | 1 |
| WTFPL OR ISC | 1 |

**合计 1152 个组件。**

## 3. 弱 copyleft（LGPL / MPL）条目与义务履行

### 3.1 LGPL（强于 MPL：整库弱 copyleft）

**含 LGPL 的条目共 4 个**（真源 `docs/dsh-integration-preflight-checklist.md` §B13 / §F7.4 要求「必须包含 2 条 LGPL」；**本清单扫出 4 条**——`sharp` 生态 2 条之外，应用镜像的 `psycopg` 系列同为 LGPL，此前未登记）：

| 组件 | 版本 | 许可证（声明值） | 所在产物 |
|---|---|---|---|
| `@img/sharp-libvips-linux-x64` | 1.3.3 | LGPL-3.0-or-later | 执行镜像（dsh / npm） |
| `@img/sharp-wasm32` | 0.35.4 | Apache-2.0 AND LGPL-3.0-or-later AND MIT | 执行镜像（dsh / npm） |
| `psycopg-binary` | 3.3.5 | LGPL-3.0-only | 应用镜像（Python） |
| `psycopg-pool` | 3.3.1 | LGPL-3.0-only | 应用镜像（Python） |

LGPL 属**弱 copyleft**：对外分发容器镜像 / 桌面产物即触发义务。本清单按「许可正文 + 可重链接 + 源码获取途径」三项逐族履行：

1. **许可正文**：`licenses/LGPL-3.0.txt`（LGPL-3.0 全文）与 `licenses/GPL-3.0.txt`（LGPL-3.0 第 3 节并入 GPL-3.0 条款，故一并提供）。
2. **可重链接（relinking）**：相关组件均以**未修改的独立包 / 独立共享库**形式随产物分发，未与我方代码静态链接、未修改其源码 ⇒ 使用方可自行替换为修改后的同版本库并重新运行：`@img/sharp-libvips-*` 对应 `lib/libvips-cpp.so.*`；`psycopg-binary` 对应其内置 libpq 二进制。
3. **源码获取途径**：上游源码公开发布，可自行取回同版本源码 —— `@img/sharp-libvips-*` ← `lovell/sharp-libvips`（内含 libvips 本体，上游 `libvips/libvips`）；`@img/sharp-wasm32` ← `lovell/sharp`；`psycopg` / `psycopg-binary` / `psycopg-pool` ← `psycopg/psycopg`。**当前交付包内不含上游源码副本**，仅提供上述公开获取途径；如需随交付包提供源码副本，请在交付前提出。

### 3.2 MPL-2.0（文件级弱 copyleft）

**含 MPL 的条目共 25 个**：

| 组件 | 版本 | 许可证（声明值） | 所在产物 |
|---|---|---|---|
| `certifi` | 2026.7.22 | Mozilla Public License 2.0 (MPL 2.0) | 应用镜像（Python） |
| `lightningcss-android-arm64` | 1.33.0 | MPL-2.0 | 前端（admin-web） |
| `lightningcss-android-arm64` | 1.33.0 | MPL-2.0 | 前端（companion-pwa） |
| `lightningcss-darwin-arm64` | 1.33.0 | MPL-2.0 | 前端（admin-web） |
| `lightningcss-darwin-arm64` | 1.33.0 | MPL-2.0 | 前端（companion-pwa） |
| `lightningcss-darwin-x64` | 1.33.0 | MPL-2.0 | 前端（admin-web） |
| `lightningcss-darwin-x64` | 1.33.0 | MPL-2.0 | 前端（companion-pwa） |
| `lightningcss-freebsd-x64` | 1.33.0 | MPL-2.0 | 前端（admin-web） |
| `lightningcss-freebsd-x64` | 1.33.0 | MPL-2.0 | 前端（companion-pwa） |
| `lightningcss-linux-arm-gnueabihf` | 1.33.0 | MPL-2.0 | 前端（admin-web） |
| `lightningcss-linux-arm-gnueabihf` | 1.33.0 | MPL-2.0 | 前端（companion-pwa） |
| `lightningcss-linux-arm64-gnu` | 1.33.0 | MPL-2.0 | 前端（admin-web） |
| `lightningcss-linux-arm64-gnu` | 1.33.0 | MPL-2.0 | 前端（companion-pwa） |
| `lightningcss-linux-arm64-musl` | 1.33.0 | MPL-2.0 | 前端（admin-web） |
| `lightningcss-linux-arm64-musl` | 1.33.0 | MPL-2.0 | 前端（companion-pwa） |
| `lightningcss-linux-x64-gnu` | 1.33.0 | MPL-2.0 | 前端（admin-web） |
| `lightningcss-linux-x64-gnu` | 1.33.0 | MPL-2.0 | 前端（companion-pwa） |
| `lightningcss-linux-x64-musl` | 1.33.0 | MPL-2.0 | 前端（admin-web） |
| `lightningcss-linux-x64-musl` | 1.33.0 | MPL-2.0 | 前端（companion-pwa） |
| `lightningcss-win32-arm64-msvc` | 1.33.0 | MPL-2.0 | 前端（admin-web） |
| `lightningcss-win32-arm64-msvc` | 1.33.0 | MPL-2.0 | 前端（companion-pwa） |
| `lightningcss-win32-x64-msvc` | 1.33.0 | MPL-2.0 | 前端（admin-web） |
| `lightningcss-win32-x64-msvc` | 1.33.0 | MPL-2.0 | 前端（companion-pwa） |
| `lightningcss` | 1.33.0 | MPL-2.0 | 前端（admin-web） |
| `lightningcss` | 1.33.0 | MPL-2.0 | 前端（companion-pwa） |

MPL-2.0 属**文件级**弱 copyleft（不是整库 copyleft）：义务只针对「被修改的 MPL 源文件」。相关组件以**未修改的独立包**形式分发 ⇒ 无「公开被修改文件」的义务；其源码可自上游公开仓库取回。**我方未修改这些组件的源码。**

> ⚠️ **正文现状（如实）**：这些组件随带的许可文件**多为「指向别的文件的说明」而非 MPL 正文**（实测 `certifi` 的 MPL 说明仅 989 字节）⇒ 本脚本**拒绝把说明当正文收录**，并在下方「未验证与边界」里登记为**需人工补权威正文**。这不影响「我方未修改」这一义务判断，但**不得**据此认为 MPL 正文已随产物齐备。

## 4. 组件清单

### 应用镜像（Python）（52 个）

| 组件 | 版本 | 许可证（声明值） |
|---|---|---|
| `amqp` | 5.3.1 | BSD License |
| `annotated-doc` | 0.0.5 | MIT |
| `annotated-types` | 0.8.0 | MIT |
| `anyio` | 4.15.1 | MIT |
| `billiard` | 4.2.4 | BSD License |
| `celery` | 5.6.3 | BSD-3-Clause |
| `certifi` | 2026.7.22 | Mozilla Public License 2.0 (MPL 2.0) |
| `cffi` | 2.1.1 | MIT-0 |
| `charset-normalizer` | 3.5.1 | MIT |
| `click` | 8.5.0 | BSD-3-Clause |
| `click-didyoumean` | 0.3.1 | MIT License |
| `click-plugins` | 1.1.1.2 | BSD License |
| `click-repl` | 0.3.0 | MIT |
| `cryptography` | 48.0.1 | Apache-2.0 OR BSD-3-Clause |
| `docker` | 7.2.0 | Apache-2.0 |
| `fastapi` | 0.141.1 | MIT |
| `h11` | 0.16.0 | MIT License |
| `httpcore` | 1.0.9 | BSD-3-Clause |
| `httptools` | 0.8.0 | MIT |
| `httpx` | 0.28.1 | BSD License |
| `idna` | 3.19 | BSD-3-Clause |
| `iniconfig` | 2.3.0 | MIT |
| `kombu` | 5.6.2 | BSD-3-Clause |
| `packaging` | 26.3 | Apache-2.0 OR BSD-2-Clause |
| `pluggy` | 1.6.0 | MIT License |
| `prompt-toolkit` | 3.0.53 | BSD License |
| `psycopg-binary` | 3.3.5 | LGPL-3.0-only |
| `psycopg-pool` | 3.3.1 | LGPL-3.0-only |
| `pycparser` | 3.0 | BSD-3-Clause |
| `pydantic` | 2.13.5 | MIT |
| `pydantic-core` | 2.46.5 | MIT |
| `pydantic-settings` | 2.15.0 | MIT |
| `pygments` | 2.21.0 | BSD-2-Clause |
| `pyjwt` | 2.14.0 | MIT |
| `pypdf` | 5.9.0 | BSD-3-Clause |
| `pytest` | 8.4.2 | MIT License |
| `python-dateutil` | 2.9.0.post0 | Apache Software License |
| `python-dotenv` | 1.2.3 | BSD-3-Clause |
| `pyyaml` | 6.0.3 | MIT License |
| `redis` | 5.3.1 | MIT License |
| `requests` | 2.34.2 | Apache Software License |
| `six` | 1.17.0 | MIT License |
| `starlette` | 1.6.0 | BSD-3-Clause |
| `typing-extensions` | 4.16.0 | PSF-2.0 |
| `typing-inspection` | 0.4.4 | MIT |
| `tzdata` | 2026.4 | Apache-2.0 |
| `tzlocal` | 5.4.4 | MIT |
| `urllib3` | 2.7.0 | MIT |
| `vine` | 5.1.0 | BSD License |
| `watchfiles` | 1.2.0 | MIT License |
| `wcwidth` | 0.8.3 | MIT |
| `websockets` | 17.1 | BSD-3-Clause |

### 执行镜像（dsh / npm）（503 个）

| 组件 | 版本 | 许可证（声明值） |
|---|---|---|
| `@agentclientprotocol/sdk` | 1.4.0 | Apache-2.0 |
| `@anthropic-ai/sdk` | 0.123.0 | MIT |
| `@aws-crypto/sha256-browser` | 5.2.0 | Apache-2.0 |
| `@aws-crypto/sha256-js` | 5.2.0 | Apache-2.0 |
| `@aws-crypto/supports-web-crypto` | 5.2.0 | Apache-2.0 |
| `@aws-crypto/util` | 5.2.0 | Apache-2.0 |
| `@aws-sdk/client-bedrock-runtime` | 3.1048.0 | Apache-2.0 |
| `@aws-sdk/core` | 3.978.0 | Apache-2.0 |
| `@aws-sdk/credential-provider-env` | 3.972.71 | Apache-2.0 |
| `@aws-sdk/credential-provider-http` | 3.972.73 | Apache-2.0 |
| `@aws-sdk/credential-provider-ini` | 3.973.16 | Apache-2.0 |
| `@aws-sdk/credential-provider-login` | 3.972.78 | Apache-2.0 |
| `@aws-sdk/credential-provider-node` | 3.972.83 | Apache-2.0 |
| `@aws-sdk/credential-provider-process` | 3.972.71 | Apache-2.0 |
| `@aws-sdk/credential-provider-sso` | 3.973.15 | Apache-2.0 |
| `@aws-sdk/credential-provider-web-identity` | 3.972.77 | Apache-2.0 |
| `@aws-sdk/eventstream-handler-node` | 3.972.34 | Apache-2.0 |
| `@aws-sdk/middleware-eventstream` | 3.972.29 | Apache-2.0 |
| `@aws-sdk/middleware-websocket` | 3.972.53 | Apache-2.0 |
| `@aws-sdk/nested-clients` | 3.997.45 | Apache-2.0 |
| `@aws-sdk/signature-v4-multi-region` | 3.996.46 | Apache-2.0 |
| `@aws-sdk/token-providers` | 3.1048.0 | Apache-2.0 |
| `@aws-sdk/token-providers` | 3.1129.0 | Apache-2.0 |
| `@aws-sdk/types` | 3.974.5 | Apache-2.0 |
| `@aws-sdk/util-locate-window` | 3.965.10 | Apache-2.0 |
| `@aws-sdk/xml-builder` | 3.972.40 | Apache-2.0 |
| `@aws/lambda-invoke-store` | 0.3.0 | Apache-2.0 |
| `@babel/code-frame` | 7.29.7 | MIT |
| `@babel/helper-validator-identifier` | 7.29.7 | MIT |
| `@babel/runtime` | 7.29.7 | MIT |
| `@deepseek-ai/cordis` | 4.0.2 | MIT |
| `@deepseek-ai/cordis-plugin-group` | 1.0.2 | MIT |
| `@deepseek-ai/cordis-plugin-hmr` | 1.0.17 | MIT |
| `@deepseek-ai/cordis-plugin-include` | 1.0.7 | MIT |
| `@deepseek-ai/cordis-plugin-loader` | 1.0.3 | MIT |
| `@deepseek-ai/cordis-plugin-timer` | 1.1.4 | MIT |
| `@deepseek-ai/cosmokit` | 1.8.3 | MIT |
| `@deepseek-ai/dsh` | 0.1.5-rc.1 | MIT |
| `@deepseek-ai/dsh-acp` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-acp-app` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-agent` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-agent-default-model` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-agent-instructions` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-agent-loop` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-agent-presets` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-agent-tool-presentation` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-anonymous-user-id` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-api-gateway` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-api-remotes` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-api-session-controller` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-api-settings-controller` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-api-workspace-controller` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-api-workspace-files` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-app-boot` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-atomic-write` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-attachment` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-attachment-local` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-authorization` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-base` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-bash-local` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-bash-sandbox` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-brand` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-chunked-list` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-connection` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-file-upload` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-hmr` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-locale` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-modules` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-resources` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-agent-preset` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-approval` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-attachment` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-brand-official` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-chat` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-commands` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-conversation` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-cordis` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-deliverables` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-directory-picker-browse` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-directory-picker-native` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-goal` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-input-trigger` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-jobs` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-layout` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-message-feedback` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-model-selection` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-open-in-app` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-permission-presets` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-plan` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-reference` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-renderer` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-schedule` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-session` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-settings` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-settings-general` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-settings-models` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-settings-plugin-inventory` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-settings-plugins` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-sidebar` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-sidebar-documentpreview` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-sidebar-files` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-sidebar-right` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-skill` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-subagent` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-theme` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-tool` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-trajectory` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-user-questions` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-workflow-run` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-client-ui-workspace` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-cmdline` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-code-runtime` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-code-runtime-worker-thread` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-command-compact` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-command-feedback` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-command-goal` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-commands` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-compaction` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-compaction-basic` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-compaction-tool-result-pruner` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-cordis-client-runner` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-cordis-host-runner` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-credentials` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-credentials-local` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-deepseek-llm-api-extensions` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-deque` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-file-reference` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-file-reference-local` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-fs` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-fs-local` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-fs-observation-policy` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-fs-sandbox` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-goal` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-goal-round-driver` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-headless` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-home-paths` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-hook-protocol` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-hooks-claude-code` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-hooks-codex` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-host-directory-picker` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-host-directory-picker-auto` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-host-directory-picker-browse` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-host-directory-picker-native` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-host-frontend-static` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-host-open-in-app` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-host-plugin-inventory` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-host-webserver` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-http-proxy` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-invariants` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-jobs` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-jobs-local` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-launch-environment` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-llm` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-llm-deepseek` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-llm-pi-ai` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-llm-retry` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-mcp-client` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-message-feedback` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-native-command` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-output-retention` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-package-manifest` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-permission-presets` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-persona` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-plan-mode` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-plugin-package-inventory-deepseek` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-pwsh-local` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-pwsh-sandbox` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-repeat-tool-reminder` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-sandbox` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-sandbox-local` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-sandbox-policy` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-sandbox-windows-acl` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-schedule` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-scope` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-sdk-app` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-sdk-jsonrpc-server` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-sdk-minimal` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-sdk-protocol` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-session` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-session-checkpoint-policy` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-session-format` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-session-format-catalog` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-session-format-v0-to-v1` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-session-format-v1-to-v2` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-session-format-v2-to-v3` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-session-log-deepseek` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-session-log-export` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-session-persistence` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-session-persistence-jsonl` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-session-projection` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-session-projection-cache` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-session-query` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-session-query-sqlite` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-session-reference` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-session-stats` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-session-telemetry` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-session-telemetry-otel` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-session-title` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-session-title-first-prompt-llm` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-session-title-llm` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-session-turn-outline` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-settings` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-settings-file` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-shell` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-shell-env` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-skill` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-skill-badge` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-skill-filesystem` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-spill` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-spill-local` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-spill-policy` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-storage` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-storage-domain` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-storage-json` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-subagent` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-subagent-fork-in-process` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-subagent-in-process-driver` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-subagent-spawn-in-process` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-subprocess` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-subprocess-local` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-system-prompt` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-terminal` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-terminal-bash` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-time-context` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-timeout` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-tmux-context` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-token-meter` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-tool-ask-user` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-tool-bash` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-tool-bash-persistent` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-tool-call-timeout-policy` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-tool-cordis` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-tool-fs` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-tool-fs-search` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-tool-goal` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-tool-jobs` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-tool-present` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-tool-pwsh` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-tool-pwsh-persistent` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-tool-ralph` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-tool-skill` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-tool-str-replace-editor` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-tool-subagent` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-tool-subagent-control` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-tool-todo` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-tool-web` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-tool-workflow` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-tools` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-typert-loader` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-typert-protocol` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-typert-registry` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-user-approval` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-user-questions` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-util-crypto` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-util-time` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-util-values` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-util-workspace-path` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-web` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-web-app` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-web-fetch-http` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-web-frontend` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-web-search-deepseek` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-webhook` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-webhook-github` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-win32-process` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-workflow` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-workflow-worker-thread` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/dsh-workspace` | 0.1.5-rc.2 | MIT |
| `@deepseek-ai/node-addon-system` | 0.1.2 | BSD-3-Clause |
| `@deepseek-ai/node-addon-system-linux-x64` | 0.1.2 | BSD-3-Clause |
| `@deepseek-ai/schemastery` | 3.18.2 | MIT |
| `@earendil-works/pi-ai` | 0.85.1 | MIT |
| `@earendil-works/pi-telemetry` | 0.85.1 | MIT |
| `@emnapi/runtime` | 1.11.3 | MIT |
| `@google/genai` | 1.52.0 | Apache-2.0 |
| `@hono/node-server` | 2.1.1 | MIT |
| `@img/colour` | 1.1.0 | MIT |
| `@img/sharp-libvips-linux-x64` | 1.3.3 | LGPL-3.0-or-later |
| `@img/sharp-linux-x64` | 0.35.4 | Apache-2.0 |
| `@img/sharp-wasm32` | 0.35.4 | Apache-2.0 AND LGPL-3.0-or-later AND MIT |
| `@joplin/turndown-plugin-gfm` | 1.0.68 | MIT |
| `@koromix/koffi-linux-x64` | 3.2.1 | MIT |
| `@mixmark-io/domino` | 2.2.0 | BSD-2-Clause |
| `@modelcontextprotocol/sdk` | 1.30.0 | MIT |
| `@octokit/openapi-types` | 29.0.1 | MIT |
| `@octokit/openapi-webhooks-types` | 12.1.0 | MIT |
| `@octokit/request-error` | 7.1.2 | MIT |
| `@octokit/types` | 18.0.0 | MIT |
| `@octokit/webhooks` | 14.2.0 | MIT |
| `@octokit/webhooks-methods` | 6.0.0 | MIT |
| `@opentelemetry/api` | 1.9.1 | Apache-2.0 |
| `@opentelemetry/api-logs` | 0.220.0 | Apache-2.0 |
| `@opentelemetry/core` | 2.11.0 | Apache-2.0 |
| `@opentelemetry/core` | 2.9.0 | Apache-2.0 |
| `@opentelemetry/exporter-logs-otlp-http` | 0.220.0 | Apache-2.0 |
| `@opentelemetry/otlp-exporter-base` | 0.220.0 | Apache-2.0 |
| `@opentelemetry/otlp-transformer` | 0.220.0 | Apache-2.0 |
| `@opentelemetry/resources` | 2.11.0 | Apache-2.0 |
| `@opentelemetry/resources` | 2.9.0 | Apache-2.0 |
| `@opentelemetry/sdk-logs` | 0.220.0 | Apache-2.0 |
| `@opentelemetry/sdk-metrics` | 2.9.0 | Apache-2.0 |
| `@opentelemetry/sdk-trace` | 2.9.0 | Apache-2.0 |
| `@opentelemetry/semantic-conventions` | 1.43.0 | Apache-2.0 |
| `@protobufjs/aspromise` | 1.1.2 | BSD-3-Clause |
| `@protobufjs/base64` | 1.1.2 | BSD-3-Clause |
| `@protobufjs/codegen` | 2.0.5 | BSD-3-Clause |
| `@protobufjs/eventemitter` | 1.1.1 | BSD-3-Clause |
| `@protobufjs/fetch` | 1.1.1 | BSD-3-Clause |
| `@protobufjs/float` | 1.0.2 | BSD-3-Clause |
| `@protobufjs/path` | 1.1.2 | BSD-3-Clause |
| `@protobufjs/pool` | 1.1.0 | BSD-3-Clause |
| `@protobufjs/utf8` | 1.1.2 | BSD-3-Clause |
| `@smithy/core` | 3.34.0 | Apache-2.0 |
| `@smithy/credential-provider-imds` | 4.5.2 | Apache-2.0 |
| `@smithy/fetch-http-handler` | 5.8.0 | Apache-2.0 |
| `@smithy/is-array-buffer` | 2.2.0 | Apache-2.0 |
| `@smithy/node-http-handler` | 4.12.1 | Apache-2.0 |
| `@smithy/node-http-handler` | 4.7.3 | Apache-2.0 |
| `@smithy/signature-v4` | 5.7.3 | Apache-2.0 |
| `@smithy/types` | 4.18.0 | Apache-2.0 |
| `@smithy/util-buffer-from` | 2.2.0 | Apache-2.0 |
| `@smithy/util-utf8` | 2.3.0 | Apache-2.0 |
| `@stablelib/base64` | 1.0.1 | MIT |
| `@standard-schema/spec` | 1.1.0 | MIT |
| `@types/node` | 22.20.2 | MIT |
| `@types/retry` | 0.12.0 | MIT |
| `@vscode/ripgrep` | 1.18.0 | MIT |
| `@vscode/ripgrep-linux-x64` | 1.18.0 | MIT |
| `@xterm/headless` | 6.0.0 | MIT |
| `accepts` | 2.0.0 | MIT |
| `agent-base` | 7.1.4 | MIT |
| `ajv` | 8.20.0 | MIT |
| `ajv-formats` | 3.0.1 | MIT |
| `argparse` | 2.0.1 | Python-2.0 |
| `base64-js` | 1.5.1 | MIT |
| `benchmark` | 1.0.0 | ISC |
| `bignumber.js` | 9.3.1 | MIT |
| `body-parser` | 2.3.0 | MIT |
| `bowser` | 2.14.1 | MIT |
| `buffer-equal-constant-time` | 1.0.1 | BSD-3-Clause |
| `bundle-name` | 4.1.0 | MIT |
| `bytes` | 3.1.2 | MIT |
| `call-bind-apply-helpers` | 1.0.2 | MIT |
| `call-bound` | 1.0.4 | MIT |
| `chokidar` | 4.0.3 | MIT |
| `chokidar` | 5.0.0 | MIT |
| `commander` | 15.0.0 | MIT |
| `compressible` | 2.0.18 | MIT |
| `compression` | 1.8.2 | MIT |
| `content-disposition` | 1.1.0 | MIT |
| `content-type` | 1.0.5 | MIT |
| `content-type` | 2.1.0 | MIT |
| `cookie` | 0.7.2 | MIT |
| `cookie-signature` | 1.2.2 | MIT |
| `cors` | 2.8.6 | MIT |
| `cross-spawn` | 7.0.6 | MIT |
| `data-uri-to-buffer` | 4.0.1 | MIT |
| `debug` | 2.6.9 | MIT |
| `debug` | 4.4.3 | MIT |
| `default-browser` | 5.5.1 | MIT |
| `default-browser-id` | 5.0.1 | MIT |
| `define-lazy-prop` | 3.0.0 | MIT |
| `depd` | 2.0.0 | MIT |
| `destroy` | 1.2.0 | MIT |
| `detect-libc` | 2.1.2 | Apache-2.0 |
| `diff` | 9.0.0 | BSD-3-Clause |
| `dunder-proto` | 1.0.1 | MIT |
| `ecdsa-sig-formatter` | 1.0.11 | Apache-2.0 |
| `ee-first` | 1.1.1 | MIT |
| `encodeurl` | 2.0.0 | MIT |
| `es-define-property` | 1.0.1 | MIT |
| `es-errors` | 1.3.0 | MIT |
| `es-object-atoms` | 1.1.2 | MIT |
| `escape-html` | 1.0.3 | MIT |
| `etag` | 1.8.1 | MIT |
| `eventsource` | 3.0.7 | MIT |
| `eventsource-parser` | 3.1.1 | MIT |
| `express` | 5.2.1 | MIT |
| `express-rate-limit` | 8.7.0 | MIT |
| `extend` | 3.0.2 | MIT |
| `fast-deep-equal` | 3.1.3 | MIT |
| `fast-sha256` | 1.3.0 | Unlicense |
| `fast-uri` | 3.1.7 | BSD-3-Clause |
| `fetch-blob` | 3.2.0 | MIT |
| `fflate` | 0.8.3 | MIT |
| `finalhandler` | 2.1.1 | MIT |
| `formdata-polyfill` | 4.0.10 | MIT |
| `forwarded` | 0.2.0 | MIT |
| `fresh` | 2.0.0 | MIT |
| `function-bind` | 1.1.2 | MIT |
| `gaxios` | 7.3.1 | Apache-2.0 |
| `gcp-metadata` | 8.1.2 | Apache-2.0 |
| `get-intrinsic` | 1.3.0 | MIT |
| `get-proto` | 1.0.1 | MIT |
| `google-auth-library` | 10.9.1 | Apache-2.0 |
| `google-logging-utils` | 1.1.3 | Apache-2.0 |
| `gopd` | 1.2.0 | MIT |
| `has-symbols` | 1.1.0 | MIT |
| `hasown` | 2.0.4 | MIT |
| `hono` | 4.13.7 | MIT |
| `http-errors` | 2.0.1 | MIT |
| `http-proxy-agent` | 7.0.2 | MIT |
| `https-proxy-agent` | 7.0.6 | MIT |
| `iconv-lite` | 0.7.3 | MIT |
| `inherits` | 2.0.4 | ISC |
| `ip-address` | 10.7.0 | MIT |
| `ipaddr.js` | 1.9.1 | MIT |
| `ipaddr.js` | 2.5.0 | MIT |
| `is-docker` | 3.0.0 | MIT |
| `is-in-ssh` | 1.0.0 | MIT |
| `is-inside-container` | 1.0.0 | MIT |
| `is-promise` | 4.0.0 | MIT |
| `is-wsl` | 3.1.1 | MIT |
| `isexe` | 2.0.0 | ISC |
| `jose` | 6.2.12 | MIT |
| `js-tokens` | 4.0.0 | MIT |
| `js-yaml` | 4.3.2 | MIT |
| `json-bigint` | 1.0.0 | MIT |
| `json-schema-to-ts` | 3.1.1 | MIT |
| `json-schema-traverse` | 1.0.0 | MIT |
| `json-schema-typed` | 8.0.2 | BSD-2-Clause |
| `jwa` | 2.0.1 | MIT |
| `jws` | 4.0.1 | MIT |
| `koffi` | 3.2.1 | MIT |
| `long` | 5.3.2 | Apache-2.0 |
| `math-intrinsics` | 1.1.0 | MIT |
| `media-typer` | 1.1.1 | MIT |
| `merge-descriptors` | 2.0.0 | MIT |
| `mime-db` | 1.54.0 | MIT |
| `mime-types` | 3.0.2 | MIT |
| `ms` | 2.0.0 | MIT |
| `ms` | 2.1.3 | MIT |
| `negotiator` | 0.6.4 | MIT |
| `negotiator` | 1.1.0 | MIT |
| `node-addon-api` | 7.1.1 | MIT |
| `node-addon-native-custom-loader` | 0.1.5 | MIT |
| `node-addon-require-builtin` | 0.1.5 | MIT |
| `node-addon-require-builtin-linux-x64-gnu` | 0.1.5 | MIT |
| `node-domexception` | 1.0.0 | MIT |
| `node-fetch` | 3.3.2 | MIT |
| `node-pty` | 1.2.0-beta.15 | MIT |
| `object-assign` | 4.1.1 | MIT |
| `object-inspect` | 1.13.4 | MIT |
| `on-finished` | 2.4.1 | MIT |
| `on-headers` | 1.1.0 | MIT |
| `once` | 1.4.0 | ISC |
| `open` | 11.0.3 | MIT |
| `openai` | 6.40.0 | Apache-2.0 |
| `p-retry` | 4.6.2 | MIT |
| `parseurl` | 1.3.3 | MIT |
| `partial-json` | 0.1.7 | MIT |
| `path-key` | 3.1.1 | MIT |
| `path-to-regexp` | 8.4.2 | MIT |
| `picocolors` | 1.1.1 | ISC |
| `picomatch` | 4.0.7 | MIT |
| `pkce-challenge` | 5.0.1 | MIT |
| `powershell-utils` | 0.1.0 | MIT |
| `powershell-utils` | 0.2.1 | MIT |
| `protobufjs` | 7.6.6 | BSD-3-Clause |
| `proxy-addr` | 2.0.7 | MIT |
| `qs` | 6.16.0 | BSD-3-Clause |
| `range-parser` | 1.3.0 | MIT |
| `raw-body` | 3.0.2 | MIT |
| `readdirp` | 4.1.2 | MIT |
| `readdirp` | 5.1.1 | MIT |
| `require-from-string` | 2.0.2 | MIT |
| `resolve.exports` | 2.0.3 | MIT |
| `retry` | 0.13.1 | MIT |
| `router` | 2.2.0 | MIT |
| `run-applescript` | 7.1.0 | MIT |
| `safe-buffer` | 5.2.1 | MIT |
| `safer-buffer` | 2.1.2 | MIT |
| `semver` | 7.8.5 | ISC |
| `send` | 1.2.1 | MIT |
| `serve-static` | 2.2.1 | MIT |
| `setprototypeof` | 1.2.0 | ISC |
| `sharp` | 0.35.4 | Apache-2.0 |
| `shebang-command` | 2.0.0 | MIT |
| `shebang-regex` | 3.0.0 | MIT |
| `side-channel` | 1.1.1 | MIT |
| `side-channel-list` | 1.0.1 | MIT |
| `side-channel-map` | 1.0.1 | MIT |
| `side-channel-weakmap` | 1.0.2 | MIT |
| `standardwebhooks` | 1.1.1 | MIT |
| `statuses` | 2.0.2 | MIT |
| `toidentifier` | 1.0.1 | MIT |
| `ts-algebra` | 2.0.0 | MIT |
| `tslib` | 2.8.1 | 0BSD |
| `turndown` | 7.2.4 | MIT |
| `type-is` | 2.1.0 | MIT |
| `typebox` | 1.3.7 | MIT |
| `undici` | 8.10.2 | MIT |
| `undici-types` | 6.21.0 | MIT |
| `unpipe` | 1.0.0 | MIT |
| `vary` | 1.1.2 | MIT |
| `web-streams-polyfill` | 3.3.3 | MIT |
| `which` | 2.0.2 | ISC |
| `wrappy` | 1.0.2 | ISC |
| `ws` | 8.21.3 | MIT |
| `wsl-utils` | 1.0.0 | MIT |
| `yaml` | 2.9.0 | ISC |
| `zod` | 4.6.2 | MIT |
| `zod-to-json-schema` | 3.25.2 | ISC |

### 前端（admin-web）（154 个）

| 组件 | 版本 | 许可证（声明值） |
|---|---|---|
| `@adobe/css-tools` | 4.5.0 | MIT |
| `@asamuzakjp/css-color` | 6.0.7 | MIT |
| `@asamuzakjp/dom-selector` | 8.3.2 | MIT |
| `@babel/code-frame` | 7.29.7 | MIT |
| `@babel/helper-validator-identifier` | 7.29.7 | MIT |
| `@babel/runtime` | 7.29.7 | MIT |
| `@bramus/specificity` | 2.4.2 | MIT |
| `@csstools/color-helpers` | 6.1.1 | MIT-0 |
| `@csstools/css-calc` | 3.3.0 | MIT |
| `@csstools/css-color-parser` | 4.2.2 | MIT |
| `@csstools/css-parser-algorithms` | 4.0.0 | MIT |
| `@csstools/css-syntax-patches-for-csstree` | 1.1.12 | MIT-0 |
| `@csstools/css-tokenizer` | 4.0.0 | MIT |
| `@exodus/bytes` | 1.15.1 | MIT |
| `@jridgewell/resolve-uri` | 3.1.2 | MIT |
| `@jridgewell/sourcemap-codec` | 1.6.0 | MIT |
| `@jridgewell/trace-mapping` | 0.3.31 | MIT |
| `@oxc-project/types` | 0.148.0 | MIT |
| `@rolldown/binding-android-arm-eabi` | 1.2.7 | MIT |
| `@rolldown/binding-android-arm64` | 1.2.7 | MIT |
| `@rolldown/binding-darwin-arm64` | 1.2.7 | MIT |
| `@rolldown/binding-darwin-x64` | 1.2.7 | MIT |
| `@rolldown/binding-freebsd-x64` | 1.2.7 | MIT |
| `@rolldown/binding-linux-arm-gnueabihf` | 1.2.7 | MIT |
| `@rolldown/binding-linux-arm64-gnu` | 1.2.7 | MIT |
| `@rolldown/binding-linux-arm64-musl` | 1.2.7 | MIT |
| `@rolldown/binding-linux-ppc64-gnu` | 1.2.7 | MIT |
| `@rolldown/binding-linux-s390x-gnu` | 1.2.7 | MIT |
| `@rolldown/binding-linux-x64-gnu` | 1.2.7 | MIT |
| `@rolldown/binding-linux-x64-musl` | 1.2.7 | MIT |
| `@rolldown/binding-openharmony-arm64` | 1.2.7 | MIT |
| `@rolldown/binding-win32-arm64-msvc` | 1.2.7 | MIT |
| `@rolldown/binding-win32-x64-msvc` | 1.2.7 | MIT |
| `@rolldown/pluginutils` | 1.0.1 | MIT |
| `@testing-library/dom` | 10.4.1 | MIT |
| `@testing-library/jest-dom` | 7.0.1 | MIT |
| `@testing-library/jest-dom/node_modules/dom-accessibility-api` | 0.6.3 | MIT |
| `@testing-library/react` | 16.3.3 | MIT |
| `@testing-library/user-event` | 14.6.7 | MIT |
| `@types/aria-query` | 5.0.4 | MIT |
| `@types/chai` | 5.2.3 | MIT |
| `@types/deep-eql` | 4.0.2 | MIT |
| `@types/estree` | 1.0.9 | MIT |
| `@types/node` | 26.4.1 | MIT |
| `@types/react` | 19.2.18 | MIT |
| `@types/react-dom` | 19.2.7 | MIT |
| `@typescript/typescript-aix-ppc64` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-darwin-arm64` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-darwin-x64` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-freebsd-arm64` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-freebsd-x64` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-linux-arm` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-linux-arm64` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-linux-loong64` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-linux-mips64el` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-linux-ppc64` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-linux-riscv64` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-linux-s390x` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-linux-x64` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-netbsd-arm64` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-netbsd-x64` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-openbsd-arm64` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-openbsd-x64` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-sunos-x64` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-win32-arm64` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-win32-x64` | 7.0.2 | Apache-2.0 |
| `@vitejs/plugin-react` | 6.1.1 | MIT |
| `@vitest/mocker` | 5.0.0 | MIT |
| `@vitest/spy` | 5.0.0 | MIT |
| `ansi-regex` | 5.0.1 | MIT |
| `ansi-styles` | 5.2.0 | MIT |
| `aria-query` | 5.3.0 | Apache-2.0 |
| `assertion-error` | 2.0.1 | MIT |
| `bidi-js` | 1.0.3 | MIT |
| `chai` | 6.2.2 | MIT |
| `css-tree` | 3.2.1 | MIT |
| `css.escape` | 1.5.1 | MIT |
| `csstype` | 3.2.3 | MIT |
| `data-urls` | 7.0.0 | MIT |
| `data-urls/node_modules/whatwg-url` | 16.0.1 | MIT |
| `decimal.js` | 10.6.0 | MIT |
| `dequal` | 2.0.3 | MIT |
| `detect-libc` | 2.1.2 | Apache-2.0 |
| `dom-accessibility-api` | 0.5.16 | MIT |
| `entities` | 8.0.0 | BSD-2-Clause |
| `es-module-lexer` | 2.3.2 | MIT |
| `estree-walker` | 3.0.3 | MIT |
| `eventsource-parser` | 4.1.1 | MIT |
| `expect-type` | 1.4.0 | Apache-2.0 |
| `fdir` | 6.5.0 | MIT |
| `fsevents` | 2.3.3 | MIT |
| `html-encoding-sniffer` | 6.0.0 | MIT |
| `indent-string` | 4.0.0 | MIT |
| `is-potential-custom-element-name` | 1.0.1 | MIT |
| `js-tokens` | 4.0.0 | MIT |
| `jsdom` | 30.0.1 | MIT |
| `lightningcss` | 1.33.0 | MPL-2.0 |
| `lightningcss-android-arm64` | 1.33.0 | MPL-2.0 |
| `lightningcss-darwin-arm64` | 1.33.0 | MPL-2.0 |
| `lightningcss-darwin-x64` | 1.33.0 | MPL-2.0 |
| `lightningcss-freebsd-x64` | 1.33.0 | MPL-2.0 |
| `lightningcss-linux-arm-gnueabihf` | 1.33.0 | MPL-2.0 |
| `lightningcss-linux-arm64-gnu` | 1.33.0 | MPL-2.0 |
| `lightningcss-linux-arm64-musl` | 1.33.0 | MPL-2.0 |
| `lightningcss-linux-x64-gnu` | 1.33.0 | MPL-2.0 |
| `lightningcss-linux-x64-musl` | 1.33.0 | MPL-2.0 |
| `lightningcss-win32-arm64-msvc` | 1.33.0 | MPL-2.0 |
| `lightningcss-win32-x64-msvc` | 1.33.0 | MPL-2.0 |
| `lru-cache` | 11.5.2 | BlueOak-1.0.0 |
| `lz-string` | 1.5.0 | MIT |
| `magic-string` | 1.2.3 | MIT |
| `mdn-data` | 2.27.1 | CC0-1.0 |
| `min-indent` | 1.0.1 | MIT |
| `nanoid` | 3.3.18 | MIT |
| `obug` | 2.1.4 | MIT |
| `parse5` | 8.0.1 | MIT |
| `picocolors` | 1.1.1 | ISC |
| `picomatch` | 4.0.7 | MIT |
| `postcss` | 8.5.28 | MIT |
| `pretty-format` | 27.5.1 | MIT |
| `punycode` | 2.3.1 | MIT |
| `react` | 19.2.8 | MIT |
| `react-dom` | 19.2.8 | MIT |
| `react-is` | 17.0.2 | MIT |
| `redent` | 3.0.0 | MIT |
| `require-from-string` | 2.0.2 | MIT |
| `rolldown` | 1.2.7 | MIT |
| `saxes` | 6.0.0 | ISC |
| `scheduler` | 0.27.0 | MIT |
| `siginfo` | 2.0.0 | ISC |
| `source-map-js` | 1.2.1 | BSD-3-Clause |
| `stackback` | 0.0.2 | MIT |
| `std-env` | 4.2.0 | MIT |
| `strip-indent` | 3.0.0 | MIT |
| `symbol-tree` | 3.2.4 | MIT |
| `tinybench` | 6.1.4 | MIT |
| `tinyexec` | 1.3.0 | MIT |
| `tinyglobby` | 0.2.17 | MIT |
| `tldts` | 7.4.11 | MIT |
| `tldts-core` | 7.4.11 | MIT |
| `tough-cookie` | 6.0.2 | BSD-3-Clause |
| `tr46` | 6.0.0 | MIT |
| `typescript` | 7.0.2 | Apache-2.0 |
| `undici` | 8.10.2 | MIT |
| `undici-types` | 8.3.0 | MIT |
| `vite` | 8.2.2 | MIT |
| `vitest` | 5.0.0 | MIT |
| `w3c-xmlserializer` | 5.0.0 | MIT |
| `webidl-conversions` | 8.0.1 | BSD-2-Clause |
| `whatwg-mimetype` | 5.0.0 | MIT |
| `whatwg-url` | 17.1.0 | MIT |
| `why-is-node-running` | 2.3.0 | MIT |
| `xml-name-validator` | 5.0.0 | Apache-2.0 |
| `xmlchars` | 2.2.0 | MIT |

### 前端（companion-pwa）（154 个）

| 组件 | 版本 | 许可证（声明值） |
|---|---|---|
| `@adobe/css-tools` | 4.5.0 | MIT |
| `@asamuzakjp/css-color` | 6.0.7 | MIT |
| `@asamuzakjp/dom-selector` | 8.3.2 | MIT |
| `@babel/code-frame` | 7.29.7 | MIT |
| `@babel/helper-validator-identifier` | 7.29.7 | MIT |
| `@babel/runtime` | 7.29.7 | MIT |
| `@bramus/specificity` | 2.4.2 | MIT |
| `@csstools/color-helpers` | 6.1.1 | MIT-0 |
| `@csstools/css-calc` | 3.3.0 | MIT |
| `@csstools/css-color-parser` | 4.2.2 | MIT |
| `@csstools/css-parser-algorithms` | 4.0.0 | MIT |
| `@csstools/css-syntax-patches-for-csstree` | 1.1.13 | MIT-0 |
| `@csstools/css-tokenizer` | 4.0.0 | MIT |
| `@exodus/bytes` | 1.15.1 | MIT |
| `@jridgewell/resolve-uri` | 3.1.2 | MIT |
| `@jridgewell/sourcemap-codec` | 1.6.0 | MIT |
| `@jridgewell/trace-mapping` | 0.3.31 | MIT |
| `@oxc-project/types` | 0.149.0 | MIT |
| `@rolldown/binding-android-arm-eabi` | 1.2.8 | MIT |
| `@rolldown/binding-android-arm64` | 1.2.8 | MIT |
| `@rolldown/binding-darwin-arm64` | 1.2.8 | MIT |
| `@rolldown/binding-darwin-x64` | 1.2.8 | MIT |
| `@rolldown/binding-freebsd-x64` | 1.2.8 | MIT |
| `@rolldown/binding-linux-arm-gnueabihf` | 1.2.8 | MIT |
| `@rolldown/binding-linux-arm64-gnu` | 1.2.8 | MIT |
| `@rolldown/binding-linux-arm64-musl` | 1.2.8 | MIT |
| `@rolldown/binding-linux-ppc64-gnu` | 1.2.8 | MIT |
| `@rolldown/binding-linux-s390x-gnu` | 1.2.8 | MIT |
| `@rolldown/binding-linux-x64-gnu` | 1.2.8 | MIT |
| `@rolldown/binding-linux-x64-musl` | 1.2.8 | MIT |
| `@rolldown/binding-openharmony-arm64` | 1.2.8 | MIT |
| `@rolldown/binding-win32-arm64-msvc` | 1.2.8 | MIT |
| `@rolldown/binding-win32-x64-msvc` | 1.2.8 | MIT |
| `@rolldown/pluginutils` | 1.0.1 | MIT |
| `@testing-library/dom` | 10.4.1 | MIT |
| `@testing-library/jest-dom` | 7.0.1 | MIT |
| `@testing-library/jest-dom/node_modules/dom-accessibility-api` | 0.6.3 | MIT |
| `@testing-library/react` | 16.3.3 | MIT |
| `@testing-library/user-event` | 14.6.7 | MIT |
| `@types/aria-query` | 5.0.4 | MIT |
| `@types/chai` | 5.2.3 | MIT |
| `@types/deep-eql` | 4.0.2 | MIT |
| `@types/estree` | 1.0.9 | MIT |
| `@types/node` | 22.20.2 | MIT |
| `@types/react` | 19.3.0 | MIT |
| `@types/react-dom` | 19.3.0 | MIT |
| `@typescript/typescript-aix-ppc64` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-darwin-arm64` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-darwin-x64` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-freebsd-arm64` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-freebsd-x64` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-linux-arm` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-linux-arm64` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-linux-loong64` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-linux-mips64el` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-linux-ppc64` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-linux-riscv64` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-linux-s390x` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-linux-x64` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-netbsd-arm64` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-netbsd-x64` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-openbsd-arm64` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-openbsd-x64` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-sunos-x64` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-win32-arm64` | 7.0.2 | Apache-2.0 |
| `@typescript/typescript-win32-x64` | 7.0.2 | Apache-2.0 |
| `@vitejs/plugin-react` | 6.1.1 | MIT |
| `@vitest/mocker` | 5.0.0 | MIT |
| `@vitest/spy` | 5.0.0 | MIT |
| `ansi-regex` | 5.0.1 | MIT |
| `ansi-styles` | 5.2.0 | MIT |
| `aria-query` | 5.3.0 | Apache-2.0 |
| `assertion-error` | 2.0.1 | MIT |
| `bidi-js` | 1.1.0 | MIT |
| `chai` | 6.2.2 | MIT |
| `css-tree` | 3.2.1 | MIT |
| `css.escape` | 1.5.1 | MIT |
| `csstype` | 3.2.3 | MIT |
| `data-urls` | 7.0.0 | MIT |
| `data-urls/node_modules/whatwg-url` | 16.0.1 | MIT |
| `decimal.js` | 10.6.0 | MIT |
| `dequal` | 2.0.3 | MIT |
| `detect-libc` | 2.1.2 | Apache-2.0 |
| `dom-accessibility-api` | 0.5.16 | MIT |
| `entities` | 8.1.0 | BSD-2-Clause |
| `es-module-lexer` | 2.3.2 | MIT |
| `estree-walker` | 3.0.3 | MIT |
| `eventsource-parser` | 4.1.1 | MIT |
| `expect-type` | 1.4.0 | Apache-2.0 |
| `fdir` | 6.5.0 | MIT |
| `fsevents` | 2.3.3 | MIT |
| `html-encoding-sniffer` | 6.0.0 | MIT |
| `indent-string` | 4.0.0 | MIT |
| `is-potential-custom-element-name` | 1.0.1 | MIT |
| `js-tokens` | 4.0.0 | MIT |
| `jsdom` | 30.0.1 | MIT |
| `lightningcss` | 1.33.0 | MPL-2.0 |
| `lightningcss-android-arm64` | 1.33.0 | MPL-2.0 |
| `lightningcss-darwin-arm64` | 1.33.0 | MPL-2.0 |
| `lightningcss-darwin-x64` | 1.33.0 | MPL-2.0 |
| `lightningcss-freebsd-x64` | 1.33.0 | MPL-2.0 |
| `lightningcss-linux-arm-gnueabihf` | 1.33.0 | MPL-2.0 |
| `lightningcss-linux-arm64-gnu` | 1.33.0 | MPL-2.0 |
| `lightningcss-linux-arm64-musl` | 1.33.0 | MPL-2.0 |
| `lightningcss-linux-x64-gnu` | 1.33.0 | MPL-2.0 |
| `lightningcss-linux-x64-musl` | 1.33.0 | MPL-2.0 |
| `lightningcss-win32-arm64-msvc` | 1.33.0 | MPL-2.0 |
| `lightningcss-win32-x64-msvc` | 1.33.0 | MPL-2.0 |
| `lru-cache` | 11.5.2 | BlueOak-1.0.0 |
| `lz-string` | 1.5.0 | MIT |
| `magic-string` | 1.3.1 | MIT |
| `mdn-data` | 2.27.1 | CC0-1.0 |
| `min-indent` | 1.0.1 | MIT |
| `nanoid` | 3.3.19 | MIT |
| `obug` | 2.2.1 | MIT |
| `parse5` | 8.0.1 | MIT |
| `picocolors` | 1.1.1 | ISC |
| `picomatch` | 4.0.7 | MIT |
| `postcss` | 8.5.28 | MIT |
| `pretty-format` | 27.5.1 | MIT |
| `punycode` | 2.3.1 | MIT |
| `react` | 19.3.0 | MIT |
| `react-dom` | 19.3.0 | MIT |
| `react-is` | 17.0.2 | MIT |
| `redent` | 3.0.0 | MIT |
| `require-from-string` | 2.0.2 | MIT |
| `rolldown` | 1.2.8 | MIT |
| `saxes` | 6.0.0 | ISC |
| `scheduler` | 0.28.0 | MIT |
| `siginfo` | 2.0.0 | ISC |
| `source-map-js` | 1.2.1 | BSD-3-Clause |
| `stackback` | 0.0.2 | MIT |
| `std-env` | 4.2.0 | MIT |
| `strip-indent` | 3.0.0 | MIT |
| `symbol-tree` | 3.2.4 | MIT |
| `tinybench` | 6.1.4 | MIT |
| `tinyexec` | 1.3.0 | MIT |
| `tinyglobby` | 0.2.17 | MIT |
| `tldts` | 7.4.12 | MIT |
| `tldts-core` | 7.4.12 | MIT |
| `tough-cookie` | 6.0.2 | BSD-3-Clause |
| `tr46` | 6.0.0 | MIT |
| `typescript` | 7.0.2 | Apache-2.0 |
| `undici` | 8.10.2 | MIT |
| `undici-types` | 6.21.0 | MIT |
| `vite` | 8.3.0 | MIT |
| `vitest` | 5.0.0 | MIT |
| `w3c-xmlserializer` | 5.0.0 | MIT |
| `webidl-conversions` | 8.0.1 | BSD-2-Clause |
| `whatwg-mimetype` | 5.0.0 | MIT |
| `whatwg-url` | 17.1.1 | MIT |
| `why-is-node-running` | 2.3.0 | MIT |
| `xml-name-validator` | 5.0.0 | Apache-2.0 |
| `xmlchars` | 2.2.0 | MIT |

### 前端（desktop）（289 个）

| 组件 | 版本 | 许可证（声明值） |
|---|---|---|
| `@electron-internal/extract-zip` | 1.0.5 | BSD-2-Clause |
| `@electron/asar` | 3.4.1 | MIT |
| `@electron/asar/node_modules/balanced-match` | 1.0.2 | MIT |
| `@electron/asar/node_modules/brace-expansion` | 1.1.18 | MIT |
| `@electron/asar/node_modules/minimatch` | 3.1.5 | ISC |
| `@electron/fuses` | 1.8.0 | MIT |
| `@electron/fuses/node_modules/fs-extra` | 9.1.0 | MIT |
| `@electron/get` | 5.1.0 | MIT |
| `@electron/notarize` | 2.5.0 | MIT |
| `@electron/notarize/node_modules/fs-extra` | 9.1.0 | MIT |
| `@electron/osx-sign` | 1.3.3 | BSD-2-Clause |
| `@electron/osx-sign/node_modules/isbinaryfile` | 4.0.10 | MIT |
| `@electron/rebuild` | 4.2.0 | MIT |
| `@electron/universal` | 2.0.3 | MIT |
| `@electron/universal/node_modules/balanced-match` | 1.0.2 | MIT |
| `@electron/universal/node_modules/brace-expansion` | 2.1.4 | MIT |
| `@electron/universal/node_modules/fs-extra` | 11.4.0 | MIT |
| `@electron/universal/node_modules/minimatch` | 9.0.9 | ISC |
| `@electron/windows-sign` | 1.2.2 | BSD-2-Clause |
| `@electron/windows-sign/node_modules/fs-extra` | 11.4.0 | MIT |
| `@isaacs/fs-minipass` | 4.0.1 | ISC |
| `@malept/cross-spawn-promise` | 2.0.0 | Apache-2.0 |
| `@malept/flatpak-bundler` | 0.4.0 | MIT |
| `@malept/flatpak-bundler/node_modules/fs-extra` | 9.1.0 | MIT |
| `@noble/hashes` | 2.4.0 | MIT |
| `@peculiar/asn1-schema` | 2.9.4 | MIT |
| `@peculiar/json-schema` | 1.1.12 | MIT |
| `@peculiar/utils` | 2.0.3 | MIT |
| `@peculiar/webcrypto` | 1.7.1 | MIT |
| `@sindresorhus/is` | 4.6.0 | MIT |
| `@szmarczak/http-timer` | 4.0.6 | MIT |
| `@types/cacheable-request` | 6.0.3 | MIT |
| `@types/debug` | 4.1.13 | MIT |
| `@types/fs-extra` | 9.0.13 | MIT |
| `@types/http-cache-semantics` | 4.2.0 | MIT |
| `@types/keyv` | 3.1.4 | MIT |
| `@types/ms` | 2.1.0 | MIT |
| `@types/node` | 24.13.4 | MIT |
| `@types/responselike` | 1.0.3 | MIT |
| `@xmldom/xmldom` | 0.8.15 | MIT |
| `abbrev` | 4.0.0 | ISC |
| `agent-base` | 7.1.4 | MIT |
| `ajv` | 8.20.0 | MIT |
| `ansi-regex` | 5.0.1 | MIT |
| `ansi-styles` | 4.3.0 | MIT |
| `app-builder-lib` | 26.15.3 | MIT |
| `app-builder-lib/node_modules/@electron/get` | 3.1.0 | MIT |
| `app-builder-lib/node_modules/@electron/get/node_modules/fs-extra` | 8.1.0 | MIT |
| `app-builder-lib/node_modules/@electron/get/node_modules/semver` | 6.3.1 | ISC |
| `app-builder-lib/node_modules/ci-info` | 4.3.1 | MIT |
| `app-builder-lib/node_modules/env-paths` | 2.2.1 | MIT |
| `app-builder-lib/node_modules/jsonfile` | 4.0.0 | MIT |
| `app-builder-lib/node_modules/semver` | 7.7.4 | ISC |
| `app-builder-lib/node_modules/universalify` | 0.1.2 | MIT |
| `argparse` | 2.0.1 | Python-2.0 |
| `asn1js` | 3.0.10 | BSD-3-Clause |
| `async` | 3.2.6 | MIT |
| `async-exit-hook` | 2.0.1 | MIT |
| `asynckit` | 0.4.0 | MIT |
| `at-least-node` | 1.0.0 | ISC |
| `aws4` | 1.13.2 | MIT |
| `balanced-match` | 4.0.4 | MIT |
| `base64-js` | 1.5.1 | MIT |
| `bluebird` | 3.7.2 | MIT |
| `boolean` | 3.2.0 | MIT |
| `brace-expansion` | 5.0.9 | MIT |
| `buffer-from` | 1.1.2 | MIT |
| `builder-util` | 26.15.3 | MIT |
| `builder-util-runtime` | 9.7.0 | MIT |
| `bytestreamjs` | 2.0.1 | BSD-3-Clause |
| `cacheable-lookup` | 5.0.4 | MIT |
| `cacheable-request` | 7.0.4 | MIT |
| `call-bind-apply-helpers` | 1.0.2 | MIT |
| `chalk` | 4.1.2 | MIT |
| `chownr` | 3.0.0 | BlueOak-1.0.0 |
| `chromium-pickle-js` | 0.2.0 | MIT |
| `ci-info` | 4.4.0 | MIT |
| `cliui` | 8.0.1 | ISC |
| `clone-response` | 1.0.3 | MIT |
| `color-convert` | 2.0.1 | MIT |
| `color-name` | 1.1.4 | MIT |
| `combined-stream` | 1.0.8 | MIT |
| `commander` | 5.1.0 | MIT |
| `compare-version` | 0.1.2 | MIT |
| `concat-map` | 0.0.1 | MIT |
| `core-util-is` | 1.0.3 | MIT |
| `cross-dirname` | 0.1.0 | MIT |
| `cross-spawn` | 7.0.6 | MIT |
| `cross-spawn/node_modules/isexe` | 2.0.0 | ISC |
| `cross-spawn/node_modules/which` | 2.0.2 | ISC |
| `debug` | 4.4.3 | MIT |
| `decompress-response` | 6.0.0 | MIT |
| `decompress-response/node_modules/mimic-response` | 3.1.0 | MIT |
| `defer-to-connect` | 2.0.1 | MIT |
| `define-data-property` | 1.1.4 | MIT |
| `define-properties` | 1.2.1 | MIT |
| `delayed-stream` | 1.0.0 | MIT |
| `detect-node` | 2.1.0 | MIT |
| `dir-compare` | 4.2.0 | MIT |
| `dir-compare/node_modules/balanced-match` | 1.0.2 | MIT |
| `dir-compare/node_modules/brace-expansion` | 1.1.18 | MIT |
| `dir-compare/node_modules/minimatch` | 3.1.5 | ISC |
| `dmg-builder` | 26.15.3 | MIT |
| `dotenv` | 16.6.1 | BSD-2-Clause |
| `dotenv-expand` | 11.0.7 | BSD-2-Clause |
| `dunder-proto` | 1.0.1 | MIT |
| `duplexer2` | 0.1.4 | BSD-3-Clause |
| `ejs` | 3.1.10 | Apache-2.0 |
| `electron` | 44.3.0 | MIT |
| `electron-builder` | 26.15.3 | MIT |
| `electron-builder-squirrel-windows` | 26.15.3 | MIT |
| `electron-publish` | 26.15.3 | MIT |
| `electron-updater` | 6.8.9 | MIT |
| `electron-updater/node_modules/semver` | 7.7.4 | ISC |
| `electron-winstaller` | 5.4.0 | MIT |
| `electron-winstaller/node_modules/fs-extra` | 7.0.1 | MIT |
| `electron-winstaller/node_modules/jsonfile` | 4.0.0 | MIT |
| `electron-winstaller/node_modules/universalify` | 0.1.2 | MIT |
| `emoji-regex` | 8.0.0 | MIT |
| `end-of-stream` | 1.4.5 | MIT |
| `env-paths` | 3.0.0 | MIT |
| `err-code` | 2.0.3 | MIT |
| `es-define-property` | 1.0.1 | MIT |
| `es-errors` | 1.3.0 | MIT |
| `es-object-atoms` | 1.1.2 | MIT |
| `es-set-tostringtag` | 2.1.0 | MIT |
| `es6-error` | 4.1.1 | MIT |
| `escalade` | 3.2.0 | MIT |
| `escape-string-regexp` | 4.0.0 | MIT |
| `exponential-backoff` | 3.1.3 | Apache-2.0 |
| `fast-deep-equal` | 3.1.3 | MIT |
| `fast-uri` | 3.1.7 | BSD-3-Clause |
| `fdir` | 6.5.0 | MIT |
| `filelist` | 1.0.6 | Apache-2.0 |
| `filelist/node_modules/balanced-match` | 1.0.2 | MIT |
| `filelist/node_modules/brace-expansion` | 2.1.4 | MIT |
| `filelist/node_modules/minimatch` | 5.1.9 | ISC |
| `form-data` | 4.0.6 | MIT |
| `fs-extra` | 10.1.0 | MIT |
| `fs.realpath` | 1.0.0 | ISC |
| `function-bind` | 1.1.2 | MIT |
| `get-caller-file` | 2.0.5 | ISC |
| `get-intrinsic` | 1.3.0 | MIT |
| `get-proto` | 1.0.1 | MIT |
| `get-stream` | 5.2.0 | MIT |
| `glob` | 7.2.3 | ISC |
| `glob/node_modules/balanced-match` | 1.0.2 | MIT |
| `glob/node_modules/brace-expansion` | 1.1.18 | MIT |
| `glob/node_modules/minimatch` | 3.1.5 | ISC |
| `global-agent` | 3.0.0 | BSD-3-Clause |
| `globalthis` | 1.0.4 | MIT |
| `gopd` | 1.2.0 | MIT |
| `got` | 11.8.6 | MIT |
| `graceful-fs` | 4.2.11 | ISC |
| `has-flag` | 4.0.0 | MIT |
| `has-property-descriptors` | 1.0.2 | MIT |
| `has-symbols` | 1.1.0 | MIT |
| `has-tostringtag` | 1.0.2 | MIT |
| `hasown` | 2.0.4 | MIT |
| `hosted-git-info` | 4.1.0 | ISC |
| `http-cache-semantics` | 4.2.0 | BSD-2-Clause |
| `http-proxy-agent` | 7.0.2 | MIT |
| `http2-wrapper` | 1.0.3 | MIT |
| `https-proxy-agent` | 7.0.6 | MIT |
| `inflight` | 1.0.6 | ISC |
| `inherits` | 2.0.4 | ISC |
| `is-fullwidth-code-point` | 3.0.0 | MIT |
| `isarray` | 1.0.0 | MIT |
| `isbinaryfile` | 5.0.7 | MIT |
| `isexe` | 3.1.5 | BlueOak-1.0.0 |
| `jake` | 10.9.4 | Apache-2.0 |
| `jiti` | 2.7.0 | MIT |
| `js-yaml` | 4.3.2 | MIT |
| `json-buffer` | 3.0.1 | MIT |
| `json-schema-traverse` | 1.0.0 | MIT |
| `json-stringify-safe` | 5.0.1 | ISC |
| `json5` | 2.2.3 | MIT |
| `jsonfile` | 6.2.1 | MIT |
| `keyv` | 4.5.4 | MIT |
| `lazy-val` | 1.0.5 | MIT |
| `lodash` | 4.18.1 | MIT |
| `lodash.escaperegexp` | 4.1.2 | MIT |
| `lodash.isequal` | 4.5.0 | MIT |
| `lowercase-keys` | 2.0.0 | MIT |
| `lru-cache` | 6.0.0 | ISC |
| `matcher` | 3.0.0 | MIT |
| `math-intrinsics` | 1.1.0 | MIT |
| `mime` | 2.6.0 | MIT |
| `mime-db` | 1.52.0 | MIT |
| `mime-types` | 2.1.35 | MIT |
| `mimic-response` | 1.0.1 | MIT |
| `minimatch` | 10.2.6 | BlueOak-1.0.0 |
| `minimist` | 1.2.8 | MIT |
| `minipass` | 7.1.3 | BlueOak-1.0.0 |
| `minizlib` | 3.1.0 | MIT |
| `mkdirp` | 0.5.6 | MIT |
| `ms` | 2.1.3 | MIT |
| `node-abi` | 4.35.0 | MIT |
| `node-api-version` | 0.2.1 | MIT |
| `node-gyp` | 12.4.0 | MIT |
| `node-gyp/node_modules/env-paths` | 2.2.1 | MIT |
| `node-gyp/node_modules/isexe` | 4.0.0 | BlueOak-1.0.0 |
| `node-gyp/node_modules/undici` | 6.28.1 | MIT |
| `node-gyp/node_modules/which` | 6.0.1 | ISC |
| `node-int64` | 0.4.0 | MIT |
| `nopt` | 9.0.0 | ISC |
| `normalize-url` | 6.1.0 | MIT |
| `object-keys` | 1.1.1 | MIT |
| `once` | 1.4.0 | ISC |
| `p-cancelable` | 2.1.1 | MIT |
| `p-limit` | 3.1.0 | MIT |
| `path-is-absolute` | 1.0.1 | MIT |
| `path-key` | 3.1.1 | MIT |
| `pe-library` | 0.4.1 | MIT |
| `picocolors` | 1.1.1 | ISC |
| `picomatch` | 4.0.7 | MIT |
| `pkijs` | 3.4.0 | BSD-3-Clause |
| `pkijs/node_modules/@noble/hashes` | 1.4.0 | MIT |
| `plist` | 3.1.0 | MIT |
| `postject` | 1.0.0-alpha.6 | MIT |
| `postject/node_modules/commander` | 9.5.0 | MIT |
| `proc-log` | 6.1.0 | ISC |
| `process-nextick-args` | 2.0.1 | MIT |
| `progress` | 2.0.3 | MIT |
| `promise-retry` | 2.0.1 | MIT |
| `proper-lockfile` | 4.1.2 | MIT |
| `pump` | 3.0.4 | MIT |
| `pvtsutils` | 1.3.6 | MIT |
| `pvutils` | 1.2.0 | MIT |
| `quick-lru` | 5.1.1 | MIT |
| `read-binary-file-arch` | 1.0.6 | MIT |
| `readable-stream` | 2.3.8 | MIT |
| `require-directory` | 2.1.1 | MIT |
| `require-from-string` | 2.0.2 | MIT |
| `resedit` | 1.7.2 | MIT |
| `resolve-alpn` | 1.2.1 | MIT |
| `responselike` | 2.0.1 | MIT |
| `retry` | 0.12.0 | MIT |
| `rimraf` | 2.6.3 | ISC |
| `roarr` | 2.15.4 | BSD-3-Clause |
| `safe-buffer` | 5.1.2 | MIT |
| `sanitize-filename` | 1.6.4 | WTFPL OR ISC |
| `sax` | 1.6.1 | BlueOak-1.0.0 |
| `semver` | 7.8.5 | ISC |
| `semver-compare` | 1.0.0 | MIT |
| `serialize-error` | 7.0.1 | MIT |
| `shebang-command` | 2.0.0 | MIT |
| `shebang-regex` | 3.0.0 | MIT |
| `signal-exit` | 3.0.7 | ISC |
| `simple-update-notifier` | 2.0.0 | MIT |
| `source-map` | 0.6.1 | BSD-3-Clause |
| `source-map-support` | 0.5.21 | MIT |
| `sprintf-js` | 1.1.3 | BSD-3-Clause |
| `stat-mode` | 1.0.0 | MIT |
| `string-width` | 4.2.3 | MIT |
| `string_decoder` | 1.1.1 | MIT |
| `strip-ansi` | 6.0.1 | MIT |
| `sumchecker` | 3.0.1 | Apache-2.0 |
| `supports-color` | 7.2.0 | MIT |
| `tar` | 7.5.22 | BlueOak-1.0.0 |
| `tar/node_modules/yallist` | 5.0.0 | BlueOak-1.0.0 |
| `temp` | 0.9.4 | MIT |
| `temp-file` | 3.4.0 | MIT |
| `tiny-async-pool` | 1.3.0 | MIT |
| `tiny-async-pool/node_modules/semver` | 5.7.2 | ISC |
| `tiny-typed-emitter` | 2.1.0 | MIT |
| `tinyglobby` | 0.2.17 | MIT |
| `tmp` | 0.2.7 | MIT |
| `tmp-promise` | 3.0.3 | MIT |
| `truncate-utf8-bytes` | 1.0.2 | WTFPL |
| `tslib` | 2.8.1 | 0BSD |
| `type-fest` | 0.13.1 | (MIT OR CC0-1.0) |
| `undici` | 7.29.1 | MIT |
| `undici-types` | 7.18.2 | MIT |
| `universalify` | 2.0.1 | MIT |
| `unzipper` | 0.12.5 | MIT |
| `unzipper/node_modules/fs-extra` | 11.3.1 | MIT |
| `utf8-byte-length` | 1.0.5 | (WTFPL OR MIT) |
| `util-deprecate` | 1.0.2 | MIT |
| `webcrypto-core` | 1.9.2 | MIT |
| `which` | 5.0.0 | ISC |
| `wrap-ansi` | 7.0.0 | MIT |
| `wrappy` | 1.0.2 | ISC |
| `xmlbuilder` | 15.1.1 | MIT |
| `y18n` | 5.0.8 | ISC |
| `yallist` | 4.0.0 | ISC |
| `yargs` | 17.7.3 | MIT |
| `yargs-parser` | 21.1.1 | ISC |
| `yocto-queue` | 0.1.0 | MIT |

## 5. 许可证正文

| 许可证 | 正文文件 |
|---|---|
| 0BSD | [`licenses/0BSD.txt`](licenses/0BSD.txt) |
| Apache Software License | [`licenses/Apache-2.0.txt`](licenses/Apache-2.0.txt) |
| Apache-2.0 | [`licenses/Apache-2.0.txt`](licenses/Apache-2.0.txt) |
| BSD License | [`licenses/BSD License.txt`](licenses/BSD License.txt) |
| BSD-2-Clause | [`licenses/BSD-2-Clause.txt`](licenses/BSD-2-Clause.txt) |
| BSD-3-Clause | [`licenses/BSD-3-Clause.txt`](licenses/BSD-3-Clause.txt) |
| GPL-3.0 | [`licenses/GPL-3.0.txt`](licenses/GPL-3.0.txt) |
| ISC | [`licenses/ISC.txt`](licenses/ISC.txt) |
| LGPL-3.0 | [`licenses/LGPL-3.0.txt`](licenses/LGPL-3.0.txt) |
| LGPL-3.0-only | [`licenses/LGPL-3.0.txt`](licenses/LGPL-3.0.txt) |
| LGPL-3.0-or-later | [`licenses/LGPL-3.0.txt`](licenses/LGPL-3.0.txt) |
| MIT | [`licenses/MIT.txt`](licenses/MIT.txt) |
| MIT License | [`licenses/MIT.txt`](licenses/MIT.txt) |
| MIT-0 | [`licenses/MIT-0.txt`](licenses/MIT-0.txt) |
| MPL-2.0 | [`licenses/MPL-2.0.txt`](licenses/MPL-2.0.txt) |
| Mozilla Public License 2.0 (MPL 2.0) | [`licenses/MPL-2.0.txt`](licenses/MPL-2.0.txt) |
| PSF-2.0 | [`licenses/PSF-2.0.txt`](licenses/PSF-2.0.txt) |
| Python-2.0 | [`licenses/Python-2.0.txt`](licenses/Python-2.0.txt) |
| Unlicense | [`licenses/Unlicense.txt`](licenses/Unlicense.txt) |

> 其余许可证（MIT / Apache-2.0 / BSD / ISC 等）的正文**随各自组件包一并分发**（安装树内各包目录下的 `LICENSE*` 文件），本文件不重复抄录。

## 6. 未验证与边界（不得读成已验）

1. 应用镜像 Python 依赖中以下包在本机安装树内**未找到 dist-info**（多为平台限定包，Linux 构建时才安装）⇒ 其许可证声明**未取证**，不得读成已核：uvloop==0.22.1
2. 许可证 `(MIT OR CC0-1.0)` 是**复合表达式** ⇒ 不为其单独收集正文（各分量的正文另按其本名收录，如 `Apache-2.0` / `BSD-2-Clause`）。
3. 许可证 `(WTFPL OR MIT)` 是**复合表达式** ⇒ 不为其单独收集正文（各分量的正文另按其本名收录，如 `Apache-2.0` / `BSD-2-Clause`）。
4. 许可证 `Apache-2.0 AND LGPL-3.0-or-later AND MIT` 是**复合表达式** ⇒ 不为其单独收集正文（各分量的正文另按其本名收录，如 `Apache-2.0` / `BSD-2-Clause`）。
5. 许可证 `Apache-2.0 OR BSD-2-Clause` 是**复合表达式** ⇒ 不为其单独收集正文（各分量的正文另按其本名收录，如 `Apache-2.0` / `BSD-2-Clause`）。
6. 许可证 `Apache-2.0 OR BSD-3-Clause` 是**复合表达式** ⇒ 不为其单独收集正文（各分量的正文另按其本名收录，如 `Apache-2.0` / `BSD-2-Clause`）。
7. 许可证 `BlueOak-1.0.0` 的正文**未能从安装树收集**（相关包未随带 LICENSE 文件）⇒ 需人工取权威原文放入 `licenses/BlueOak-1.0.0.txt`。
8. 许可证 `CC0-1.0` 的正文**未能从安装树收集**（相关包未随带 LICENSE 文件）⇒ 需人工取权威原文放入 `licenses/CC0-1.0.txt`。
9. 许可证 `WTFPL` 的正文**未能从安装树收集**（相关包未随带 LICENSE 文件）⇒ 需人工取权威原文放入 `licenses/WTFPL.txt`。
10. 许可证 `WTFPL OR ISC` 是**复合表达式** ⇒ 不为其单独收集正文（各分量的正文另按其本名收录，如 `Apache-2.0` / `BSD-2-Clause`）。

以下三项**未做**，属已知边界，**不构成「许可已全部核对」的承诺**：

1. **未逐包比对「声明值与许可证正文一致」**：本清单登记的是各组件的**声明值**（`package.json` 的 `license` / `METADATA` 的许可证字段），未逐包阅读 500+ 份 LICENSE 正文做交叉核验。
2. **未做「镜像内二次扫描」**：本清单扫的是**锁文件与安装树**，不是**镜像层**——执行镜像（含 dsh）尚未构建（`WORKBENCH_EXEC_IMAGE_DIGEST` 留空、仓库内无该镜像定义）⇒ 镜像内实际集合与本文清单的一致性**未验证**；镜像定义冻结后须在镜像内复跑同一扫描。
3. **未评估各许可证的商标 / 专利条款**（如 Apache-2.0 §6 商标限制、BSD 的背书条款）对具体交付形态的影响；如需对外交付，建议按交付合同做一次法务复核。

> 本清单**只登记核对状态与证据来源，不构成任何代码复用或采购决定**。
