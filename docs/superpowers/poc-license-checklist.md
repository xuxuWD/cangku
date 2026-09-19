# Harness POC 许可证与供应链清单

> **更新（2026-09-13，第五轮复核 R5-6 回填）**：打 **✅** 者为**已读上游 `LICENSE` 原文**。Codex / Hermes / OpenClaw 三项于 2026-09-13 **经 GitHub 官方 API 重新取回**并在下表记录 **SHA**——其中 **Hermes 原依据为「本机知识库笔记 + 用户已在使用」，不构成许可证证据**（第五轮独立复核阻断项 R5-6），已更正；未打 ✅ 者仍为「必查项」。
>
> **另（2026-09-13，用户批准）**：文末新增 **【基础设施组件纳管】** 一节（MinIO / PostgreSQL+pgvector / Redis / MinIO 备选实现）—— 起因是 **MinIO 的 AGPLv3 事实**，且**基础设施组件此前从未纳入本清单**（检索 `MinIO` / `PostgreSQL` / `Redis` / `AGPL` **零命中**）。

| 项目 | 当前定位 | 许可证（核对状态） | 必查项 |
|---|---|---|---|
| DeerFlow | 通用长任务候选 | MIT（**待核对正文**） | 依赖 SBOM、固定版本、容器镜像 |
| Codex App Server/Worker（`openai/codex`） | FDE 执行候选 | **Apache-2.0 ✅ 已核对**（`LICENSE` 原文经 GitHub 官方 API 取回，**SHA `4606e72e…`**；`Copyright 2025 OpenAI`） | Rust 依赖、沙箱与商标声明；**Apache-2.0 §4(d) 的 `NOTICE` 义务**须在复用前核对 |
| **Hermes Agent**（[`NousResearch/hermes-agent`](https://github.com/NousResearch/hermes-agent)） | 成长能力参考/隔离 Worker | **MIT ✅ 已核对**（`LICENSE` 原文经 GitHub 官方 API 取回，**SHA `75410e73…`**：`MIT License` + `Copyright (c) 2025 Nous Research`）。**R5-6 更正**：本条原先把"确认依据"写成"本机知识库笔记 + 用户已在使用"，**那不属于许可证证据**（第五轮独立复核阻断项 R5-6）→ 现已改为**上游 `LICENSE` 原文直取**；上游定位另由仓库自述 "The agent that grows with you" 与知识库笔记互相印证 | 模型/工具依赖、数据边界；**注意**：其生态含大量第三方扩展仓库（`hermes-agent-self-evolution`、`hermes-webui`、`oh-my-hermes` 等），**逐个核对另行进行** |
| DeepSeek Harness | 实验对照 | MIT（**待核对正文**） | 开发预览破坏性变更 |
| **OpenClaw**（`openclaw/openclaw`） | 能力参照（电脑控制 / 浏览器 / 沙箱） | **MIT ✅ 已核对**（`LICENSE` 原文经 GitHub 官方 API 取回，**SHA `ebaebf7c…`**：`Copyright (c) 2026 OpenClaw Foundation`；原文另注 "Third-party notices … recorded in `THIRD_PARTY_NOTICES.md`"） | 依赖与第三方声明；**须排查是否存在 `enterprise/`-类的非开源 carve-out**；**若日后 vendor 其 `computer-use` 脚本集，须连带核对 `THIRD_PARTY_NOTICES.md` 并产出我方 `THIRD-PARTY-NOTICES`（宪法 12.3）**；该候选**未经评审、未启用**（`moat-boundaries.md` §3 / `capability-ownership-map.md` §2 第 30 行） |
| **OpenMausBot**（`milind-soni/OpenMausBot`） | 交互模式与契约纪律参照 | **Apache-2.0 ✅ 已核对**（`LICENSE` 原文）；**⚠️ `enterprise/` 目录为独立非开源许可**（生产需 license key、禁止托管给第三方 / 白标）→ **不得引用** | 第三方打包件（含 MPL-2.0 × 7）、`NOTICE` 义务 |
| OpenWorkBuddy（`CatCatUncle/openworkbuddy`） | 交互模式参照 | **PolyForm Noncommercial 1.0.0 ✅ 已核对**（商用需另行授权） | 仅可提炼信息架构与交互模式，**禁止搬运代码 / 资源 / 文案 / 视觉** |
| EvoFlow | 不作为商业底座 | Evovex AI Non-Commercial License ✅（既有结论） | — |

> **口径**：本清单只登记**核对状态与来源**，**不构成任何代码复用决定**——任何复用须另过许可评审并产出 `THIRD-PARTY-NOTICES`（宪法 12.3）。每次升级都要重新生成 SBOM、扫描漏洞、核对许可证和回滚版本；任何无法完成审查的依赖不得进入生产路径。

> ✅ **`THIRD-PARTY-NOTICES` 已产出（2026-09-19，C 项交付物）**：根目录
> [`THIRD-PARTY-NOTICES.md`](../../THIRD-PARTY-NOTICES.md)，由
> [`scripts/generate_third_party_notices.py`](../../scripts/generate_third_party_notices.py) **可重跑生成**
> （守护：`tests/test_third_party_notices.py`，12 条）。**扫描 1152 个组件**，覆盖四类随交付物分发的产物：
> 应用镜像（`requirements.lock` 53 项）、执行镜像（dsh npm 安装树）、管理台 / 伴侣端 / 桌面端（各自 lockfile）。
>
> **🔴 扫描查出一处此前未登记的 copyleft**：**`psycopg-binary@3.3.5` 与 `psycopg-pool@3.3.1` 为
> LGPL-3.0-only**（在应用镜像内、随交付物分发）——此前只登记了 `sharp` 生态的 2 条 LGPL，
> 真源 `docs/dsh-integration-preflight-checklist.md` §B13 / §F7.4 的「必须含 2 条 LGPL」口径**漏了这两条**。
> 现清单共列 **4 条 LGPL**，并**逐族**写明「许可正文 + 可重链接 + 源码获取途径」三项义务（`sharp` 族与 `psycopg` 族）。
>
> 许可正文落在 [`licenses/`](../../licenses)：`LGPL-3.0` / `GPL-3.0` / `MPL-2.0` 为**预置权威原文**、
> **缺失即 fail-closed**（这些上游往往不随带正文：`@img/sharp-libvips-*` 无 LICENSE 文件、`certifi` 的 MPL
> 只有 989 字节的「指路说明」）；其余由脚本从安装树**按内容特征校验后**原文收集，
> **拒绝把「指路说明」当正文**（实测反例：`cryptography` 的 `LICENSE` 仅 197 字节）。
>
> **未验证（不得读成已验）**：① 未逐包比对「声明值与许可证正文一致」；② **镜像内二次扫描未做**
> （执行镜像尚未构建、`WORKBENCH_EXEC_IMAGE_DIGEST` 留空）；③ BlueOak-1.0.0 / CC0-1.0 / WTFPL 等正文未齐
> —— 以上三项均在产物「未验证与边界」逐条登记。

> **本清单曾要求、但长期未落地的两项**（「版本锁定归档」与「**退出方案**」）现由 [`docs/key-dependency-autonomy-plan.md`](../key-dependency-autonomy-plan.md) 承接——含四问退出方案模板、分层策略与 P0 执行项（归档 + **断网构建演练**）。**"退出方案"在本项目 4 处文档里被要求过，此前一次也没做**，该缺口由该方案收口。

---

## 基础设施组件纳管（2026-09-13 新增）

> **为什么新增**：2026-09-13 排查 MinIO 镜像可得性时，其启动 banner 声明 `License: GNU AGPLv3`；随后在本清单内检索 `MinIO` / `PostgreSQL` / `Redis` / `AGPL` **零命中** ⇒ **基础设施组件（`capability-ownership-map.md` 里的"B 类·用轮子"）此前从未进入许可核对范围**。本节**只登记核对状态与证据来源**，**不构成任何许可结论**。

| 组件（钉死版本） | 当前定位 | 许可证（核对状态 + **证据来源**） | 风险与必查项 |
|---|---|---|---|
| **MinIO**<br>`quay.io/minio/minio:RELEASE.2025-04-22T22-12-26Z`<br>digest `sha256:a1ea29fa…015e` | 对象存储（B 类，`capability-ownership-map.md` 第 24 行） | **GNU AGPLv3**（✅ **证据已于 2026-09-13 升级为上游原文**：`minio/minio` `LICENSE`，blob SHA `be3f7b28e564e7dd05eaf59d64adba1a4065ac0e`，commit `7aac2a2c5b7c882e68c1ce017d8256be2feea27f` = **AGPL-3.0 全文**，与镜像启动 banner 一致；镜像内无 `/LICENSE` 文件故此前只能依 banner） | ✅ **已于 2026-09-13 替换为 SeaweedFS（Apache-2.0）—— 本组件不再在用**（见 [`key-dependency-autonomy-plan.md`](../key-dependency-autonomy-plan.md) §11.12）。**以下为存档的原风险**：AGPLv3 含**网络交互条款（§13）**。**仅使用未修改的 MinIO 作自托管服务**时，通常只须向网络交互方提供**该服务自身源码**（上游源码本公开）；**但若我方修改 MinIO 并对外提供网络服务，义务显著上升**。**必查项**：① 从上游取回许可正文并归档；② 形成"**是否接受 AGPL 组件进生产**"的明确结论；③ 若将来魔改，须重评或改走宽松许可的 S3 兼容实现（候选**许可均待核**） |
| **PostgreSQL 16 + pgvector**<br>`pgvector/pgvector:0.8.0-pg16`<br>digest `sha256:a132765e…8bc9` | 数据库（B 类） | **PostgreSQL License（类 BSD、宽松）** ✅ **已从镜像内取证**：`/usr/share/doc/pgvector/LICENSE` 原文含 `Portions Copyright (c) 1996-2024, PostgreSQL Global Development Group` / `… Permission to use, copy, modify, and distribute this software … without fee`；PG 本体见 `/usr/share/doc/postgresql-16/copyright`，标 **`License: PostgreSQL`** | ① 升级 PG 大版本时**重新取证**；② `pgvector` 与 PG 本体**两处许可分别留档**；③ 现结论**支持商用**（宽松许可），但**仍须在产出 `THIRD-PARTY-NOTICES` 时登载**（宪法 12.3） |
| **Redis**<br>`redis:7.4-alpine`（内含 **Redis server v7.4.11**）<br>digest `sha256:ff02b58f…eadf` | 缓存/队列（B 类） | 🔴 **RSALv2 + SSPLv1 双许可**（**source-available，非 OSI 开源**）—— ✅ **已取证（2026-09-13）**：**上游 `LICENSE.txt` 原文 @ tag `7.4.11`**（`raw.githubusercontent.com/redis/redis/7.4.11/LICENSE.txt`）开头即写："Starting on March 20th, 2024 … contributions under version 7.4 and subsequent releases … subject to the user's choice of the **RSALv2** or the **SSPLv1**"。⚠️ **该镜像内无任何许可文件**（`/usr/share/licenses` 不存在、`/usr/share/doc` 空、`find` 零命中）⇒ 本条**只能走上游原文取证** | 🔴 **风险（比 MinIO 的 AGPL 更直接）**：RSALv2 明文限制 —— "**You may not make the functionality of the Software or a Modified version available to third parties as a service**"，并列举"**enabling third parties to interact with the functionality … remotely through a computer network**"与"**offering a product or service, the value of which entirely or primarily derives from the value of the Software**"；**SSPLv1** 另含**"服务化即须开源整个服务对应源码"**的义务。⇒ **若本工作台将来以服务形态交付/供第三方使用，须先过合规判断**（**内部自用与对外交付是两种情形，不得混为一谈**）。**必查项**：① 形成"**是否接受 source-available（RSALv2/SSPLv1）组件进生产**"的明确结论；② 评估替代/升级方向 —— **已取证，见下方【Redis 相关许可的四条可选路径】**；③ 无论升级或替换，**都要重跑基线**（后端 1434 与相关回归） |
| MinIO 备选实现<br>（SeaweedFS / Garage / Ceph RGW） | 换实现候选（[`key-dependency-autonomy-plan.md`](../key-dependency-autonomy-plan.md) §11.8 选项②） | ✅ **已完成一轮取证（2026-09-13，见下方【MinIO 替代候选取证】）**：**SeaweedFS = Apache-2.0 ✅ 可用**；**Garage = AGPL-3.0 ❌ 排除**；**Ceph RGW = LGPL-2.1/LGPL-3 ⚠️ 弱 copyleft，按原则应排除或需你明确例外** | ✅ **已选定 ① 并落地（2026-09-13）⇒ 本项闭环**（选型已定、替换已实施并验证）—— 见下方【MinIO 替代候选取证】与 [`key-dependency-autonomy-plan.md`](../key-dependency-autonomy-plan.md) §11.12 |

#### MinIO 替代候选取证（2026-09-13）

> 取证方式同前：**上游仓库原文**（GitHub 官方 API `get_file_contents`）。因取的是**默认分支**，**证据以返回的 commit SHA 钉死**；真替换时仍应按**钉死的 tag / 镜像**复核。

| 候选 | 许可 | 取证（含 commit） | 按"不引入 copyleft" |
| --- | --- | --- | --- |
| **SeaweedFS**（`seaweedfs/seaweedfs`） | **Apache License 2.0** ✅ | `LICENSE`，blob `c9c58bb50326065bd516d433f284cc865b97362a`，commit `99d2479528b1a61706368c060e74e39ea0756ec5`（`Copyright 2025 Chris Lu`） | ✅ **可用**（宽松许可） |
| **Garage**（`deuxfleurs-org/garage`，**GitHub 是镜像**，主仓库在其自建 Gitea） | **GNU AGPLv3** ❌ | `LICENSE`，blob `be3f7b28e564e7dd05eaf59d64adba1a4065ac0e`，commit `871a472da0180e5cfe75c4438da7f1e273e82f1b`（分支 `main-v2`） | ❌ **排除**（与 MinIO 同类：强 copyleft + 网络交互条款） |
| **Ceph / RGW**（`ceph/ceph`） | **LGPL-2.1 或 LGPL-3**（`Files: *`，`Copyright (c) 2004-2010 Sage Weil`）；文件级另有 BSD-3 / Apache-2.0 / MIT / Boost / CC0 / zlib 型条款；**并含两个 AGPL-3.0 脚本** | `COPYING`，blob `52394f5bcb57bb5ae5bf80f047862cc89dd8b50a`，commit `a2c71ca92826a08801d9e5e7668c5a14e94cce91` | ⚠️ **LGPL 属弱 copyleft** ⇒ 按"不引入 copyleft"**应排除**；**若你愿对"独立部署的 LGPL 服务"网开一面，须由你明确**（另：运维体量在候选中最大） |

> **结论（只陈述事实，不替你裁决）**：在**已取证**的候选中，**SeaweedFS（Apache-2.0）是唯一"宽松许可 + 轻量"的选择**；Garage 与 Ceph 分别因 **AGPL** / **LGPL（弱 copyleft）**落在你已定的原则之外 —— 后者是否例外，**须你明确**。**本轮不动任何代码/配置。**
>
> ✅ **用户已选 ①（SeaweedFS）并已落地（2026-09-13）**：compose 服务 `minio`→`seaweedfs`、镜像钉到 `chrislusf/seaweedfs:4.46@sha256:08d51613…5b62`；**S3 真实冒烟（boto3）全部通过**；**遥测已显式关闭**。详见 [`key-dependency-autonomy-plan.md`](../key-dependency-autonomy-plan.md) §11.12。
>
> ✅ **按钉死版本的许可复核（2026-09-13）**：`seaweedfs/seaweedfs` `LICENSE` **@ tag `4.46`**，blob `c9c58bb50326065bd516d433f284cc865b97362a`，commit `d997fba1575583a89cf0cc50dc0150642286c86d` = **Apache-2.0**；**与镜像自报构建 commit `d997fba15` 一致** ⇒ 证据链闭合。（且仓库根目录**无 `enterprise/` 类专有目录**。）

> **🔑 一个显著影响成本的事实（2026-09-13 全仓查证）**：**`object_storage_url` 目前没有任何应用代码在用** —— 全仓检索只命中 `app/settings.py`（默认值 `http://localhost:9000`）、`scripts/staging_preflight.py`（仅检查"对象存储独立主机"）、`.env.example` / `.env.staging.example` / `docker-compose.app.yml` 与相关测试；**没有 S3 客户端调用**（无 `boto3` / `put_object` / 预签名等）。⇒ **MinIO 现处"已声明、未接入"状态**，**此刻替换代价最低**；**一旦真正接入对象存储读写，替换成本会显著上升** ⇒ 建议**尽早定选型**。

#### Redis 相关许可的四条可选路径（2026-09-13 取证）

> 取证方式：**上游仓库原文**（Redis 走 `raw.githubusercontent.com`；Valkey 走 GitHub 官方 API `get_file_contents`）。**每条都写明取值 ref / tag** —— 许可随版本变化，**不可跨版本套用**。

| 路径 | 许可 | 取证（**含 ref**） | 注意 |
| --- | --- | --- | --- |
| **① 维持 `7.4.11`** | **RSALv2 / SSPLv1**（二选一，**不含 AGPLv3**） | ✅ `redis/redis` `LICENSE.txt` **@ tag `7.4.11`** | **对外以服务形态提供时受限**（原文见上表）；须先有合规结论 |
| **② 升级 Redis 8.x 并选 AGPLv3** | **三选一**：RSALv2 **或** SSPLv1 **或** **AGPLv3** | ✅ `redis/redis` `LICENSE.txt` **@ tag `8.0.0`**，原文："…subject to your choice of: (a) the Redis Source Available License v2 (RSALv2); or (b) the Server Side Public License v1 (SSPLv1); or (c) the **GNU Affero General Public License v3 (AGPLv3)**" | ⚠️ **不是"8.x 即开源"**——是**允许你选** AGPLv3；**AGPLv3 自身的义务（网络交互条款）同样需要结论**；升级须**重跑基线 1434** |
| **③ 回退到 Redis 7.2（BSD-3）** | **BSD-3** | ✅ 同上文件 **@ tag `8.0.0`** 内注明："**Redis Open Source 7.2 and prior releases remain subject to the BSDv3 clause license**" | ⚠️ 这是**降级**：丢掉 7.4/8 的修复与新特性，**须评估安全与功能影响** |
| **④ 换 Valkey** | **BSD 3-Clause** ✅ | ✅ `valkey-io/valkey` `COPYING` **@ `refs/heads/unstable`**（SHA `a2782ea7…`）：`BSD 3-Clause License` + `Copyright (c) 2024-present, Valkey contributors` / `Copyright (c) 2006-2020, Redis Ltd.`；另核 `LICENSES/` **仅含宽松许可**（Apache-2.0 / BSD-2-Clause / BSD-3-Clause / BSL-1.0 / CC0-1.0 / ISC / MIT / Zlib），**无任何 copyleft** | ⚠️ **本次取的是 `unstable` 分支（浮动 ref）**，属**方向性证据**；真替换时须**按钉死的 tag/镜像重新取证**。另需验证**兼容性**（命令/协议/持久化格式/客户端库）与**镜像可得性**，并**重跑基线** |

> **我不在这四条里替你做选择** —— 选哪条取决于"**内部自用还是对外交付**""**是否接受 AGPLv3 义务**""**愿不愿承担降级/替换成本**"。上表只把**事实与取证 ref** 摆齐。

> **✅ 决策留痕（2026-09-13，用户裁决）**：**选定路径 ④ —— 换成 Valkey（BSD 3-Clause）**。
> **依据（用户原话口径）**：① 交付形态 = **"现在内部，将来可能对外"**；② 对 copyleft 的态度 = **"宁换实现也不引入 copyleft"**。
> **推导**：因"**将来可能对外**" ⇒ **排除 ①**（RSALv2 的"提供给第三方作为服务"届时会实质命中）；因"**不引入 copyleft**" ⇒ **排除 ②**（AGPLv3 义务）**与 ③**（降级只换来另一种许可，且安全性更差）⇒ **只剩 ④**。
> ✅ **已实施（2026-09-13，同日）**：[`docker-compose.yml`](../../docker-compose.yml) 已换为 **`valkey/valkey:8-alpine@sha256:d2e18f34…43d1`**（**Valkey 8.1.10**）；**用项目自身 `RedisStreamEventBus` 真连 Valkey 跑 Streams 语义 ⇒ `10/10 PASS`**（**含反假测试：坏地址必红；含对照组：同一套对 Redis 7.4.11 亦 10/10**）；回归 **`1434 passed` + `compileall` 通过**。
> **本项的许可证据（按钉死版本）**：上游 `COPYING` **@ tag `8.1.10`**（blob SHA `2254cb05c4434c5d2ec74282eca5b0d00323e228`）= **两份 BSD 3-Clause**（`Copyright (c) 2024-present, Valkey contributors` / `Copyright (c) 2006-2020, Redis Ltd.`）⇒ **无 copyleft**。**Redis/RSALv2 这条风险就此闭合。**（详见 [`key-dependency-autonomy-plan.md`](../key-dependency-autonomy-plan.md) §11.11）

> **⚠️ 同一原则的连带影响（MinIO）**：按"宁换实现也不引入 copyleft"，**MinIO（AGPLv3）也需在对外交付前评估替换**。候选（SeaweedFS / Ceph RGW / Garage 等）**许可一律未核** —— **不得凭印象认定某个候选就是宽松许可**（例如其中有的项目本身就是强 copyleft）。⇒ 属**独立议题**，需**另行取证 + 另行裁决**；**本轮未做**。

> **关闭条件**：上表标"**未核**"的项**逐条取证**后，本节方可视为完成。**在此之前，不得默认"基础设施组件无许可问题"**（对应 [`key-dependency-autonomy-plan.md`](../key-dependency-autonomy-plan.md) §8 第 7 项与门禁清单 §B16）。

> **口径**：与上表同口径——只登记**核对状态与证据来源**，**不构成代码复用或采购决定**；**证据级别必须写明**（**镜像内原文 / 镜像 banner / 上游 API**），**不同级别不得混作同等强度**。**本次新增不改变任何既有结论。**
