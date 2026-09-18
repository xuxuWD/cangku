# 单机 staging 建置方案（方案 A：闲置台式机 · Windows 10 22H2 · Docker Desktop）

> **用途**：把一台**闲置台式机**（i5-14400 / 16 GB / 512 GB SSD / Windows 10 22H2）建成「公司工作台」的**单机 staging**，用于组 1「真实环境验收」的只读核验（1.3–1.5）、迁移/备份演练（1.6）、跨租户与并发探针（1.7/1.8）等项。
> **执行方式（红线）**：**AI 不连 staging**。你在这台台式机上按本文照做、把**每步自查命令的输出**回传给我，由我判读并给下一步；本文所有命令按 **PowerShell 5.1**（Win10 默认）与 **PS 语法（用 `;` 不用 `&&`）** 写成。
> **真源关系**：本文是**执行层**方案（怎么做）；判据归 [`docs/staging-acceptance-checklist.md`](staging-acceptance-checklist.md)、输入账归 [`docs/infra-input-request.md`](infra-input-request.md)、只读命令归 [`docs/readonly-verification-runbook.md`](readonly-verification-runbook.md)。三者冲突时以真源为准并回写。
> **状态**：**未执行**（本方案 2026-09-16 产出，等待按步执行；任何步骤均以「已回传输出 + 判读通过」才算完成）。
> **2026-09-18 更新（执行前校准）**：仓库迁移已由 34 增至 **39**（新增 `035_crm_core` / `036_conversation_stream` / `037_run_artifacts` / `038_conversation_mode_and_soft_delete` / `039_conversation_members`）⇒ 本文原先写死的「迁移 34 项」期望已改为**「与仓库 `migrations/*.sql` 数量一致（当前 39）」**（涉及 Step 5 ② 与 Step 7 ① 两处判据，另 §1.4 总览一格）；`WORKBENCH_APPLIED_MIGRATIONS` 仍由 Step 5 从库内实际读数回填（不手写），故其余步骤无需改动。

---

## 1. 范围与约定

### 1.1 做什么 / 不做什么 / 影响什么

| 项 | 内容 |
| --- | --- |
| **做什么** | ① 台式机基础软件就绪（WSL2 / Docker Desktop / Git / Python 3.12 / PostgreSQL 客户端）；② 四件基础设施 + embedding 服务 + 三进程应用**全容器化**起栈（postgres / redis / seaweedfs / embedding / app / worker / beat）；③ 账号就绪（超管 + 只读账号 + 探针账号）；④ 预检四连与只读核验（1.3–1.5）；⑤ 备份/恢复演练前置（1.6，需另授权） |
| **不做什么** | ① **不动**开发机现有环境（并行不冲突）；② **不接**公网（不开 80/443、不做 DNS、不做 TLS 反代）；③ **不外扩** SeaweedFS 控制台 9001（维持仅本机）；④ **不伪造**外部 Runtime（RAGFlow / AgentScope / DeerFlow / Codex Worker / Hermes）的就绪声明——没接入就如实 fail（见 §12 D4）；⑤ 不改基础编排与 `docker-compose.app.yml`（本方案只新增 `docker-compose.staging.yml` 与 `docker-compose.embedding.yml`，见 §2.3）；⑥ 不做压测（1.8）与真实执行（dsh）——各自需**单独授权** |
| **影响什么** | 仓库新增 2 个文件（`docker-compose.staging.yml` 只覆盖端口绑定；`docker-compose.embedding.yml` 定义 embedding 服务：镜像钉 digest、模型只读挂载、仅宿主回环）；台式机新装软件、预下载 embedding 模型（≈1.2 GB）与 Docker 卷（`workbench-*` 三卷 + 应用数据卷）；**仓库代码零改动** |

### 1.2 执行方式与红线

1. **写操作三授权点**：Step 5（构建镜像 + 启动应用服务——**启动即跑迁移**）、Step 6（创建账号，写库）、Step 8（备份/恢复演练）。到点我会明确说「可以执行」再动手。
2. **密钥纪律**：`D:\workbench-secrets\staging.env` 含全部密钥——**不进仓库、不进聊天、不贴截图**；自查回传一律只回「长度 / 是否互不相同 / True-False」，**不回值**。口令与令牌一律 `***`。
3. **每步三步走**：执行命令 → 跑自查 → 回传输出（失败就把**报错原文一个字不改**贴回来，我先判读再让你往下走）。**不要跳步**、不要「顺手」多跑命令。
4. **三轮刹车**沿用：同一问题三轮未解决即停手换现场，不猜着改。

### 1.3 路径与变量约定

| 变量 | 含义 | 本方案取值 |
| --- | --- | --- |
| `$IP` | 台式机**局域网 IPv4**（Step 0 取得） | 例 `192.168.1.50`（以实测为准） |
| `$ROOT` | 工作目录 | `D:\workbench`（**若无 D 盘**：全文把 `D:\workbench` 换成 `C:\workbench`，并在执行记录里登记「单盘」） |
| `$APP` | 仓库克隆目录 | `$ROOT\app` |
| `$SECRETS` | 密钥目录（受 ACL 保护） | `D:\workbench-secrets` |
| `$PINNED_SHA` | 本方案钉住的提交 | **本批推送取证后由我方给出**；在它给定前不要执行 Step 2 |
| `$MODEL_DIR` | embedding 模型目录（Step 2 预下载） | `$ROOT\models\Qwen3-Embedding-0.6B` |
| 命令行 | 除注明「开发机」外，全部在**台式机**的 **PowerShell（管理员）**中执行 | |

### 1.4 步骤总览

| 步 | 内容 | 写操作 | 预计回传 |
| --- | --- | --- | --- |
| Step 0 | 机器自查（版本/虚拟化/端口/磁盘/IP） | 否 | 7 段输出 |
| Step 1 | 基础软件（WSL2/Docker/Git/Python/PG 客户端） | 是（安装） | 版本号清单 |
| Step 2 | 取材料（clone + 钉 SHA + venv + httpx + **embedding 模型预下载**） | 否 | SHA、版本与模型目录 |
| Step 3 | 密钥与 `staging.env`（7 把密钥 + 载入器） | 否 | 长度/唯一性核对 |
| Step 4 | 起基础设施（pg/redis/objects/**embedding**）+ 防火墙 | 是（起容器） | `ps` + 五项探活 |
| Step 5 | **【授权点】**构建镜像 + 起应用栈 + 回填两变量 | 是（迁移） | health/迁移全量（**与仓库 `migrations/*.sql` 数量一致，2026-09-18 现为 39**）/worker/beat |
| Step 6 | **【授权点】**账号（超管/只读/探针） | 是（写库） | 登录与属性读数 |
| Step 7 | 预检四连 + 只读核验（1.3–1.5） | 否 | 四份报告 + SQL 输出 |
| Step 8 | **【授权点 · 待前置】**备份/恢复演练（1.6） | 是 | drill 四阶段输出 |

---

## 2. 拓扑与服务账

### 2.1 拓扑

```
开发机（现在的这台，不动）                    台式机（staging，新增）
┌────────────────────────   LAN（局域网）   ┌──────────────────────────────────┐
│ 浏览器/curl/探针脚本     │ ──────────────▶ │  Windows 10 22H2                  │
│ psql / pg_dump(可选)     │   $IP:5432/6379   │  └ Docker Desktop（WSL2 后端）    │
────────────────────────┘   :9000/:8000      │      ├ postgres（pgvector）:5432  │
                                              │      ├ redis（valkey）    :6379  │
                                              │      ├ seaweedfs（S3）    :9000  │
                                              │      ├ embedding（TEI）   :8080  │
                                              │      ├ app（uvicorn）     :8000  │
                                              │      ├ worker（celery）           │
                                              │      └ beat（celery beat）        │
                                              └──────────────────────────────────┘
```

- **验收机 = 开发机**：探针脚本（`cross_tenant_probe` / `staging_concurrency_probe`）与 `psql` 在**开发机**上跑也可；也可全部在台式机上跑（命令里的 `$IP` 换成 `127.0.0.1` 仅限本机自查，**判据命令必须用 `$IP`**——预检脚本对 `localhost/127.0.0.1` 是 fail-closed 的，见 §2.3）。
- **embedding 不走局域网**：`embedding` 仅在 compose 容器网络内被 app 以服务名寻址（`http://embedding:8080`），宿主侧只绑 `127.0.0.1:8080` 供调试——`$IP:8080` 不可达，防火墙放行清单与 `netstat` 判据均不含 8080（§7.4/7.5）。

### 2.2 服务与端口账（基础两文件不改；`embedding` 来自本方案新增的 `docker-compose.embedding.yml`）

| 服务 | 镜像（钉 digest） | 容器内端口 | 宿主绑定（基础文件） | 本方案追加绑定 | 用途 |
| --- | --- | --- | --- | --- | --- |
| postgres | `pgvector/pgvector:0.8.0-pg16@sha256:a132765e…` | 5432 | `127.0.0.1:5432` | `$IP:5432` | 库（迁移/pgvector/只读核验/备份） |
| redis | `valkey/valkey:8-alpine@sha256:d2e18f34…` | 6379 | `127.0.0.1:6379` | `$IP:6379` | broker/限流计数 |
| seaweedfs | `chrislusf/seaweedfs:4.46@sha256:08d51613…` | 9000（S3）/ 8888（控制台） | `127.0.0.1:9000`、`127.0.0.1:9001` | `$IP:9000` | 对象存储（**9001 不外扩**） |
| app | `workbench-app:<版本>`（本地构建） | 8000 | `127.0.0.1:8000` | `$IP:8000` | HTTP 入口；**唯一跑迁移的进程** |
| worker | 同 app 镜像 | — | — | — | Celery worker（`--concurrency=2`） |
| beat | 同 app 镜像 | — | — | — | Celery beat（独立进程） |
| embedding | `ghcr.io/huggingface/text-embeddings-inference:cpu-1.9@sha256:2538ea1c…`（新增文件 `docker-compose.embedding.yml`） | 8080 | `127.0.0.1:8080`（新文件自带） | **不追加**（不暴露局域网） | P3 记忆层 embedding（Qwen3-Embedding-0.6B，CPU；模型只读挂载） |

### 2.3 地址约定：为什么全用局域网 IP、为什么新增端口覆盖文件

- **预检是 fail-closed 的**：`scripts/staging_preflight.py` 的「PostgreSQL / Redis / 对象存储 独立主机」三项，要求地址主机名**非空且不在** `{localhost, 127.0.0.1, ::1, 0.0.0.0}` 内。因此 `staging.env` 里登记的服务地址**一律写成 `$IP`**（对开发机而言这台台式机就是**独立主机**）——这同时让「跨机真实可达」成立。
- **基础编排只绑 `127.0.0.1`**（单机开发姿态），跨机访问不到 ⇒ 新增 [`docker-compose.staging.yml`](../docker-compose.staging.yml)：`ports` 属多值选项，override 中为**追加**，把 5432/6379/9000/8000 **再绑一份到 `$IP`**；基础文件的 `127.0.0.1` 绑定保持不变，**9001 不追加**（维持仅本机）。
- **绑定地址无默认值**：`${WORKBENCH_STAGING_BIND_IP:?…}` 缺值即在 compose 阶段显式报错（fail-closed），杜绝「漏配时悄悄绑到通配地址」。
- **收窄暴露面**：入站再套一层 Windows 防火墙，仅放行「本地子网 / 专用网络」（§7.4）。
- **embedding 只在容器网络内**：app 容器以服务名 `http://embedding:8080` 访问 embedding；宿主侧只绑 `127.0.0.1:8080`（调试用），`docker-compose.staging.yml` **不为它追加 `$IP` 绑定**——局域网不可达是有意为之（P3 记忆层数据不出内网，也不扩大暴露面）。
- ⚠️ **同一变量的两种口径**（本方案的唯一「反直觉点」，先理解再动手）：
  - **容器内**：`docker-compose.app.yml` 里 app/worker/beat 的连接串是**硬编码服务名**（`@postgres:5432`、`@redis:6379`、`http://seaweedfs:9000`），**不读** `staging.env` 的 `WORKBENCH_DATABASE_URL`；
  - **宿主侧脚本**（预检 / `psql` / drill）：读环境变量，**必须**用 `$IP` 版本。
  - 二者指向同一批容器，不冲突；`staging.env` 里的 `WORKBENCH_*_URL` 只服务宿主侧。
  - **embedding 是例外**：`WORKBENCH_EMBEDDING_BASE_URL` 写在 `staging.env` 里但值是**服务名** `http://embedding:8080`——它由 compose 经 `--env-file` 读入后注入 app 容器；宿主侧验收脚本（`scripts/`）不访问 embedding，所以**不写** `$IP` 版本。

---

## 3. Step 0 · 机器自查（只读，不改任何东西）

在台式机「管理员 PowerShell」执行：

```powershell
# ① OS 版本：期望 10.0.19045（Win10 22H2）
[System.Environment]::OSVersion.Version.ToString()

# ② CPU / 内存：期望 i5-14400 / 约 16.0 GB
Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores
[math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)

# ③ 虚拟化支持：期望 True（关了就装不了 WSL2）
(Get-CimInstance Win32_Processor).VirtualizationFirmwareEnabled

# ④ 目标端口占用：期望**无输出**（有输出＝被占，先记下进程再回报）
Get-NetTCPConnection -LocalPort 5432,6379,9000,8000,9001,8080 -State Listen -ErrorAction SilentlyContinue |
  Select-Object LocalAddress, LocalPort, OwningProcess

# ⑤ 系统盘可用空间：期望 ≥100 GB
Get-PSDrive C | Select-Object @{n='FreeGB'; e={[math]::Round($_.Free/1GB,1)}}

# ⑥ 局域网 IPv4（排除 127.* 与 169.254.*）：记下 AddressFamily=IPv4 的那个地址＝$IP
Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object { $_.IPAddress -ne '127.0.0.1' -and $_.IPAddress -notlike '169.254.*' } |
  Select-Object IPAddress, InterfaceAlias, PrefixOrigin

# ⑦ 网络位置类型：期望 Private（若是 Public，见 7.4 的先改后放行）
Get-NetConnectionProfile | Select-Object InterfaceAlias, NetworkCategory
```

**回传**：以上 7 段输出。**判读要点**：②内存**约 16** 属正常（核显共享显存会让 `TotalPhysicalMemory` 略低于 16.0）；③为 `False` 需先进 BIOS 打开 VT-x；④若有占用（常见 5432/8000），告诉我进程名，我给停用命令。

---

## 4. Step 1 · 基础软件

> 全部在台式机上执行；安装类命令需管理员 PowerShell。**每条装完立即跑对应自查。**

### 4.1 WSL2

```powershell
wsl --status        # 期望：默认版本 2
# 若尚未安装（报错或提示未启用）：
wsl --install       # 会要求重启；重启后重跑 wsl --status 确认「默认版本: 2」
```

### 4.2 Docker Desktop（WSL2 后端）

```powershell
winget install --exact --id Docker.DockerDesktop --accept-source-agreements --accept-package-agreements
# 安装后启动 Docker Desktop（开始菜单），首次启动等鲸鱼图标变绿：
docker version          # 期望：Client 与 Server 两段都有；Server 的 Os/Arch 为 linux/amd64
docker run --rm hello-world    # 期望："Hello from Docker!" 后正常退出
```
若 `docker version` 报「cannot connect」：先确认 Docker Desktop 已启动且设置里 **Use the WSL 2 based engine** 已勾选（默认）。

### 4.3 Git

```powershell
winget install --exact --id Git.Git --accept-source-agreements --accept-package-agreements
# 新开一个 PowerShell（刷新 PATH）后：
git --version
```

### 4.4 Python 3.12（宿主脚本用；`pyproject.toml` 要求 ≥3.11）

```powershell
winget install --exact --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
# 新开一个 PowerShell 后：
py -3.12 --version      # 期望 Python 3.12.x
```

### 4.5 PostgreSQL **客户端**（I2：`psql` / `pg_dump` / `pg_restore`；**只装客户端，不启服务**）

```powershell
winget install --exact --id PostgreSQL.PostgreSQL.16 --accept-source-agreements --accept-package-agreements
# ⚠️ 官方安装器会自带并**自动启动**一个 PostgreSQL Windows 服务，占用 5432，必须停掉：
Get-Service *postgres* | Stop-Service
Get-Service *postgres* | Set-Service -StartupType Disabled
Get-Service *postgres* | Select-Object Name, Status, StartType   # 期望：Stopped / Disabled

# 客户端三件套（若提示找不到命令，见下）
psql --version; pg_dump --version; pg_restore --version
```

- 找不到命令时，把 bin 目录加进当前会话（并记下这个目录，以后每次用客户端前都要确认）：
  ```powershell
  Test-Path 'C:\Program Files\PostgreSQL\16\bin\psql.exe'   # 期望 True
  $env:Path += ';C:\Program Files\PostgreSQL\16\bin'
  psql --version
  ```
  （路径若不同以实际安装目录为准；装到别处就把上面的路径换成实际值。）

### 4.6 WSL 资源上限（16 GB 机器留一半给 Windows）

```powershell
# 用无 BOM UTF-8 写入 C:\Users\<你的用户名>\.wslconfig
$wslConfig = Join-Path $env:USERPROFILE '.wslconfig'
$body = "[wsl2]`nmemory=8GB`nprocessors=4`n"
[System.IO.File]::WriteAllText($wslConfig, $body, (New-Object System.Text.UTF8Encoding $false))
wsl --shutdown        # 生效（会重启 WSL；Docker Desktop 会提示重启引擎，点 Restart）
# 生效后自查：
docker info --format '{{.MemTotal}}'   # 期望约 8.6e+09（≈8 GiB）
```

**回传**：`wsl --status` 默认版本、`docker version` 的 Server 段两行、`git/psql/pg_dump/pg_restore/py -3.12` 版本号、PG 服务 Status/StartType、`docker info` 的内存数。

---

## 5. Step 2 · 取材料（只读）

```powershell
New-Item -ItemType Directory -Force -Path D:\workbench | Out-Null
cd D:\workbench
git clone https://github.com/xuxuWD/cangku.git app
cd D:\workbench\app
git checkout $PINNED_SHA      # ← 把我给出的 40 位 SHA 填在这里（不引号）
git rev-parse HEAD            # 期望：与 $PINNED_SHA 逐字符一致
```

> 仓库为 **public**，clone 无需凭据。`$PINNED_SHA` 未给出前**不要**开始本步。

宿主脚本用的最小环境（`httpx`〔验收脚本〕+ `huggingface_hub`〔embedding 模型预下载〕）：

```powershell
cd D:\workbench\app
py -3.12 -m venv .venv-accept
.\.venv-accept\Scripts\python.exe -m pip install --upgrade pip
.\.venv-accept\Scripts\python.exe -m pip install "httpx>=0.28,<1"
.\.venv-accept\Scripts\python.exe -c "import httpx, sys; print(sys.version); print(httpx.__version__)"
```

embedding 模型预下载（≈1.2 GB；**宿主下载、容器只读挂载**——容器内不做联网下载，避免启动期外部不确定性）：

```powershell
$env:HF_ENDPOINT = 'https://hf-mirror.com'   # 国内镜像，避免直连低速/超时
.\.venv-accept\Scripts\python.exe -m pip install "huggingface_hub>=0.30,<1"
$modelDir = 'D:\workbench\models\Qwen3-Embedding-0.6B'
New-Item -ItemType Directory -Force -Path $modelDir | Out-Null
.\.venv-accept\Scripts\python.exe -c "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen3-Embedding-0.6B', local_dir='D:/workbench/models/Qwen3-Embedding-0.6B')"
# 自查：文件清单与合计大小（应含 config.json / model 权重 / tokenizer 及 1_Pooling/ 等）
Get-ChildItem $modelDir | Select-Object Name
[math]::Round((Get-ChildItem $modelDir -Recurse -File | Measure-Object Length -Sum).Sum / 1GB, 2)
```

**回传**：`git rev-parse HEAD` 输出、python 版本与 httpx 版本、**模型目录文件清单与合计 GB**。

---

## 6. Step 3 · 密钥与 `staging.env`（不打印、不进仓库）

> **前置（E1 已定案 2026-09-16）**：embedding 采用**台式机自包含**（方案 A）——由 `docker-compose.embedding.yml` 随**固定四 `-f` 组合**在 Step 4 启动（TEI CPU 镜像 + Qwen3-Embedding-0.6B 模型只读挂载）。compose 对 `WORKBENCH_EMBEDDING_BASE_URL`（值为容器内服务名）与 `WORKBENCH_EMBEDDING_MODEL_DIR`（Step 2 预下载目录）双双 `:?` 必填——缺值即在 compose 阶段 fail-closed 报错（这是设计而非故障）。

### 6.1 建密钥目录并锁权限（管理员 PowerShell）

```powershell
$SECRETS = 'D:\workbench-secrets'
New-Item -ItemType Directory -Force -Path $SECRETS | Out-Null
icacls $SECRETS /inheritance:r /grant:r "$env:USERNAME:(OI)(CI)F"
```

### 6.2 生成 7 把密钥（只存当前窗口内存，**不打印完整值**）

```powershell
function New-Secret([int]$n = 48) {
  -join ((48..57) + (65..90) + (97..122) | Get-Random -Count $n | ForEach-Object { [char]$_ })
}
$DB_PW       = New-Secret 40   # postgres 应用账号
$MINIO_PW    = New-Secret 40   # 对象存储（JSON 安全字符：无引号/反斜杠，SeaweedFS s3.json 依赖）
$AUTH_SECRET = New-Secret 48   # 会话签名（≥32）
$BACKUP_KEY  = New-Secret 48   # 备份加密密钥（≥32，须 ≠ AUTH_SECRET）
$BOOTSTRAP   = New-Secret 48   # 首个超管引导口令
$RO_PW       = New-Secret 40   # 只读库账号 workbench_ro
$ARCHIVE_KEY = New-Secret 48   # 备份**落盘归档**加密（第三把，不进服务配置）

# 核对（只回传这两个输出，不要回传值）：
@($DB_PW,$MINIO_PW,$AUTH_SECRET,$BACKUP_KEY,$BOOTSTRAP,$RO_PW,$ARCHIVE_KEY) | ForEach-Object { $_.Length }
(@($DB_PW,$MINIO_PW,$AUTH_SECRET,$BACKUP_KEY,$BOOTSTRAP,$RO_PW,$ARCHIVE_KEY) | Select-Object -Unique).Count
# 期望：40 40 48 48 48 40 48；第二行 = 7（7 把互不相同）
```

### 6.3 写入 `staging.env`（无 BOM UTF-8；**同一窗口**执行，用上一步的变量）

```powershell
$IP = '192.168.x.y'      # ← 换成 Step 0 ⑥ 取得的局域网 IPv4
$envFile = Join-Path $SECRETS 'staging.env'
$body = @"
# 单机 staging 环境（方案 A）—— 本文件含密钥：不进仓库、不进聊天、不贴截图
WORKBENCH_ENV=staging
WORKBENCH_STAGING_ID=customer-a-isolated
WORKBENCH_STAGING_TENANT_ID=tenant-staging-a
WORKBENCH_STORAGE_BACKEND=postgres

# 绑定地址（compose 端口覆盖用；缺值即报错）
WORKBENCH_STAGING_BIND_IP=$IP

# 宿主侧脚本连接串（预检 / psql / drill；主机＝局域网 IP，满足"独立主机"判据）
WORKBENCH_DATABASE_URL=postgresql+psycopg://workbench:$DB_PW@$IP:5432/workbench
WORKBENCH_REDIS_URL=redis://$IP:6379/0
WORKBENCH_OBJECT_STORAGE_URL=http://$IP:9000
WORKBENCH_OBJECT_NAMESPACE=staging-customer-a

# 容器侧必填（compose 读取）
WORKBENCH_DB_PASSWORD=$DB_PW
WORKBENCH_MINIO_USER=workbench
WORKBENCH_MINIO_PASSWORD=$MINIO_PW
WORKBENCH_AUTH_SECRET=$AUTH_SECRET
WORKBENCH_BACKUP_ENCRYPTION_KEY=$BACKUP_KEY
WORKBENCH_BOOTSTRAP_TOKEN=$BOOTSTRAP
WORKBENCH_RO_PASSWORD=$RO_PW
WORKBENCH_ARCHIVE_KEY=$ARCHIVE_KEY

# embedding 服务（E1 已定案：台式机自包含——容器内以服务名寻址；compose 缺值即 fail-closed）
WORKBENCH_EMBEDDING_BASE_URL=http://embedding:8080
# embedding 模型目录（Step 2 预下载后只读挂载进容器；$ROOT 若非 D:\workbench 则同步改）
WORKBENCH_EMBEDDING_MODEL_DIR=D:/workbench/models/Qwen3-Embedding-0.6B
WORKBENCH_EMBEDDING_TIMEOUT_SECONDS=10
WORKBENCH_EMBEDDING_MAX_TOKENS=8192
WORKBENCH_MEMORY_DAILY_BUDGET_CENTS=0

# 交付元数据（如实登记：本轮未接外部 Runtime，版本表只登记 mock）
WORKBENCH_RETENTION_POLICY={"tasks":180,"audit":730}
WORKBENCH_RUNTIME_VERSIONS={"mock":"0.1.0"}

# 以下两项由 Step 5 回填
WORKBENCH_APPLIED_MIGRATIONS=
WORKBENCH_APP_IMAGE=workbench-app:unset
"@
[System.IO.File]::WriteAllText($envFile, $body, (New-Object System.Text.UTF8Encoding $false))
```

> `WORKBENCH_EMBEDDING_BASE_URL` 已按定案**直接写在模板里**（`http://embedding:8080`——容器内服务名寻址，非 `$IP`），无需再补值；`WORKBENCH_EMBEDDING_MODEL_DIR` 指向 Step 2 的预下载目录。

### 6.4 写「载入器」（每个新窗口都要先 dot-source 它）

```powershell
$loader = Join-Path $SECRETS 'load-env.ps1'
$loaderBody = @'
param([string]$Path = 'D:\workbench-secrets\staging.env')
Get-Content -LiteralPath $Path -Encoding UTF8 | ForEach-Object {
  $line = $_.Trim()
  if ($line -eq '' -or $line.StartsWith('#')) { return }
  $idx = $line.IndexOf('=')
  if ($idx -lt 1) { return }
  $name  = $line.Substring(0, $idx).Trim().TrimStart([char]0xFEFF)
  $value = $line.Substring($idx + 1).Trim()
  [Environment]::SetEnvironmentVariable($name, $value, 'Process')
}
'@
[System.IO.File]::WriteAllText($loader, $loaderBody, (New-Object System.Text.UTF8Encoding $false))
```

### 6.5 自查（回传）

```powershell
. D:\workbench-secrets\load-env.ps1
$env:WORKBENCH_ENV; $env:WORKBENCH_STAGING_BIND_IP; $env:WORKBENCH_OBJECT_NAMESPACE
@('WORKBENCH_DB_PASSWORD','WORKBENCH_MINIO_PASSWORD','WORKBENCH_AUTH_SECRET','WORKBENCH_BACKUP_ENCRYPTION_KEY','WORKBENCH_BOOTSTRAP_TOKEN','WORKBENCH_EMBEDDING_BASE_URL','WORKBENCH_EMBEDDING_MODEL_DIR') |
  ForEach-Object { "$_=" + [Environment]::GetEnvironmentVariable($_).Length }
# 期望：前三个回显值；密钥行显示长度（40/40/48/48/48），embedding 地址 21、模型目录 41，不含值
```

> **自查要点**：密钥行只显示**长度**；若 embedding 地址行或模型目录行为 `0`，Step 4 会在 compose 阶段 fail-closed（`:?` 必填）——回 6.3 补齐后再继续。

---

## 7. Step 4 · 起基础设施（postgres / redis / seaweedfs / embedding）+ 防火墙

### 7.1 起四件基础设施（含 embedding）

```powershell
. D:\workbench-secrets\load-env.ps1
cd D:\workbench\app
docker compose --env-file D:\workbench-secrets\staging.env `
  -f docker-compose.yml -f docker-compose.embedding.yml -f docker-compose.app.yml -f docker-compose.staging.yml `
  up -d postgres redis seaweedfs embedding
```

> **固定四 `-f` 组合**（后续所有 compose 命令同）：① 明明只起基础设施也要带 `docker-compose.app.yml`——`docker-compose.staging.yml` 里包含 `app` 服务的端口覆盖，**缺 app 文件时该服务定义不完整、compose 直接报错**；② `docker-compose.embedding.yml` 必须与 app 在**同一次调用**里（同一 compose 项目 ⇒ 同一网络），app 容器才能按服务名 `embedding` 解析到它。

### 7.2 自查 A：容器状态

```powershell
docker compose --env-file D:\workbench-secrets\staging.env `
  -f docker-compose.yml -f docker-compose.embedding.yml -f docker-compose.app.yml -f docker-compose.staging.yml ps
# 期望：postgres / redis / seaweedfs / embedding 四个 Up
```

### 7.3 自查 B：五项探活（①②④ 带 `$IP` 跨机读数；③⑤ 为服务级活性）

```powershell
# ① PostgreSQL：能连上并报告版本
$env:PGPASSWORD = $env:WORKBENCH_DB_PASSWORD
psql "postgresql://workbench@$($env:WORKBENCH_STAGING_BIND_IP):5432/workbench" -c "SELECT version();"
# ② pgvector「可安装」（注意：此刻迁移未跑，查的是 pg_available_extensions，不是 pg_extension）
psql "postgresql://workbench@$($env:WORKBENCH_STAGING_BIND_IP):5432/workbench" `
  -c "SELECT name, default_version FROM pg_available_extensions WHERE name='vector';"
# 期望：一行（name=vector）
# ③ Redis（valkey）
docker compose --env-file D:\workbench-secrets\staging.env `
  -f docker-compose.yml -f docker-compose.embedding.yml -f docker-compose.app.yml -f docker-compose.staging.yml `
  exec redis valkey-cli ping
# 期望：PONG
# ④ 对象存储（S3 端点活着即可：返回任意 HTTP 状态码都算通，000/超时=不通）
curl.exe -s -o NUL -w "%{http_code}`n" http://127.0.0.1:9000/
curl.exe -s -o NUL -w "%{http_code}`n" "http://$($env:WORKBENCH_STAGING_BIND_IP):9000/"
# ⑤ embedding（TEI）：/health=200；/v1/embeddings 返回 1024 维（首次启动加载模型需 30–60 秒，未就绪先等再试）
curl.exe -s -o NUL -w "%{http_code}`n" http://127.0.0.1:8080/health
$embBody = '{"model":"","input":["staging embedding 探活"]}'
$emb = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8080/v1/embeddings -ContentType "application/json" -Body $embBody
$emb.data[0].embedding.Count
# 期望：200 与 1024；维度 ≠1024 或报错就**停手**，把原始输出贴回判读
```

### 7.4 防火墙：入站只放行「本地子网 / 专用网络」（管理员 PowerShell）

```powershell
# 若 Step 0 ⑦ 显示 Public，先把该网卡改成 Private：
Get-NetConnectionProfile | Where-Object { $_.NetworkCategory -eq 'Public' } |
  Set-NetConnectionProfile -NetworkCategory Private

# 入站端口 5432/6379/9000/8000 四个——**不放行 8080**（embedding 只在容器网络内被 app
# 以服务名寻址；宿主侧仅 127.0.0.1 调试，不向局域网暴露）
New-NetFirewallRule -DisplayName "workbench-staging-inbound" -Direction Inbound -Action Allow `
  -Protocol TCP -LocalPort 5432,6379,9000,8000 -Profile Private -RemoteAddress LocalSubnet
Get-NetFirewallRule -DisplayName "workbench-staging-inbound" | Select-Object DisplayName, Enabled, Profile
```

### 7.5 自查 C：绑定面（确认没有裸奔到所有网卡）

```powershell
netstat -ano | Select-String ":5432|:6379|:9000|:8000|:8080"
# 期望：能看到 127.0.0.1:5432 与 $IP:5432 两类绑定；:8080 只应出现 127.0.0.1（不出现 $IP:8080）
# 若只见 0.0.0.0:5432（Docker Desktop 端口代理粒度问题）：
#   → 不改配置，以 7.4 防火墙规则收窄为准，并在执行记录里登记（见 §12 D3）
```

**回传**：`ps` 输出、五项探活原始输出、防火墙规则行、`netstat` 过滤结果。

---

## 8. Step 5 ·【授权点】构建镜像与起应用栈

> **此步启动即自动跑迁移**（app 是唯一跑迁移的进程），属写操作——**等我明确授权**再执行。

### 8.1 构建带版本标签的镜像

```powershell
cd D:\workbench\app
$ver = (git describe --tags --always)
$rev = (git rev-parse HEAD)
docker build --build-arg WORKBENCH_IMAGE_VERSION=$ver --build-arg WORKBENCH_IMAGE_REVISION=$rev -t workbench-app:$ver .
docker image inspect workbench-app:$ver --format '{{json .Config.Labels}}'
# 期望：输出含 org.opencontainers.image.version / .revision，且 revision = $rev
```

### 8.2 回填 `staging.env` 两个变量

```powershell
$envFile = 'D:\workbench-secrets\staging.env'
$content = Get-Content $envFile -Raw -Encoding UTF8
$content = $content -replace '(?m)^WORKBENCH_APP_IMAGE=.*$', "WORKBENCH_APP_IMAGE=workbench-app:$ver"
[System.IO.File]::WriteAllText($envFile, $content, (New-Object System.Text.UTF8Encoding $false))
# 核对：
Select-String -Path $envFile -Pattern '^WORKBENCH_APP_IMAGE='
```

（`WORKBENCH_APPLIED_MIGRATIONS` 在 8.4 从库里读出后回填。）

### 8.3 起应用栈（app / worker / beat）

```powershell
. D:\workbench-secrets\load-env.ps1
cd D:\workbench\app
docker compose --env-file D:\workbench-secrets\staging.env `
  -f docker-compose.yml -f docker-compose.embedding.yml -f docker-compose.app.yml -f docker-compose.staging.yml `
  up -d --no-build
docker compose --env-file D:\workbench-secrets\staging.env `
  -f docker-compose.yml -f docker-compose.embedding.yml -f docker-compose.app.yml -f docker-compose.staging.yml ps
# 期望：app / worker 显示 healthy（beat 无 healthcheck，Up 即可；embedding 已在 Step 4 起好，本次不动它）
```

### 8.4 自查（**逐条回传**）

```powershell
# ① 应用健康（本机 + 跨机两种）：期望 200 与 {"status":"ok"}（以实际返回为准）
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health | ConvertTo-Json -Compress
Invoke-RestMethod "http://$($env:WORKBENCH_STAGING_BIND_IP):8000/api/v1/health" | ConvertTo-Json -Compress

# ② 迁移是否全部落地（I6 读数；2026-09-18 校准：以仓库 migrations/*.sql 数量为准，现为 39）：
$env:PGPASSWORD = $env:WORKBENCH_DB_PASSWORD
psql "postgresql://workbench@$($env:WORKBENCH_STAGING_BIND_IP):5432/workbench" `
  -c "SELECT count(*) FROM workbench_schema_migrations;"
# 期望：与仓库 migrations/*.sql 文件数一致（当前 39）

# ③ pgvector 扩展是否已启用（I4 复查；与 7.3 ② 的"可安装"不同，这里要「有一行」）：
psql "postgresql://workbench@$($env:WORKBENCH_STAGING_BIND_IP):5432/workbench" `
  -c "SELECT extname, extversion FROM pg_extension WHERE extname='vector';"

# ④ 迁移清单回填（逗号拼接，写回 staging.env）：
$list = (psql "postgresql://workbench@$($env:WORKBENCH_STAGING_BIND_IP):5432/workbench" -t -A `
  -c "SELECT version FROM workbench_schema_migrations ORDER BY version;" |
  Where-Object { $_.Trim() -ne '' }) -join ','
$envFile = 'D:\workbench-secrets\staging.env'
$content = Get-Content $envFile -Raw -Encoding UTF8
$content = $content -replace '(?m)^WORKBENCH_APPLIED_MIGRATIONS=.*$', "WORKBENCH_APPLIED_MIGRATIONS=$list"
[System.IO.File]::WriteAllText($envFile, $content, (New-Object System.Text.UTF8Encoding $false))
Select-String -Path $envFile -Pattern '^WORKBENCH_APPLIED_MIGRATIONS=' | ForEach-Object { $_.Line.Substring(0, 60) + "…" }

# ⑤ worker 就绪：期望日志含 "ready."
docker compose --env-file D:\workbench-secrets\staging.env `
  -f docker-compose.yml -f docker-compose.embedding.yml -f docker-compose.app.yml -f docker-compose.staging.yml logs worker --tail 40

# ⑥ beat 在派发：期望日志含 "Sending due task"（首次启动会立即派发一轮）
docker compose --env-file D:\workbench-secrets\staging.env `
  -f docker-compose.yml -f docker-compose.embedding.yml -f docker-compose.app.yml -f docker-compose.staging.yml logs beat --tail 40

# ⑦ 若 ① 失败，看 app 日志定位（把原始报错贴回来）：
docker compose --env-file D:\workbench-secrets\staging.env `
  -f docker-compose.yml -f docker-compose.embedding.yml -f docker-compose.app.yml -f docker-compose.staging.yml logs app --tail 80
```

**回传**：①②③ 原始输出、④ 的前 60 字符、⑤⑥ 关键行（或 ⑦ 的报错原文）。

---

## 9. Step 6 ·【授权点】账号就绪（写库）

> 三件事：**超管**（含 TOTP 绑定）、**只读库账号** `workbench_ro`、**探针账号**（第二手机号）。命令与坑的依据：`docs/readonly-verification-runbook.md` §1.1/§1.3 + 2026-09-12 / 2026-09-16 本机实测。

### 9.1 建超管（首次部署：bootstrap）

```powershell
. D:\workbench-secrets\load-env.ps1
$BASE = "http://$($env:WORKBENCH_STAGING_BIND_IP):8000"
$body = @{
  phone = "<手机号①>"; password = "<≥10 位口令>"; position = "owner"; full_name = "owner"
  tenant_id = "tenant-staging-a"; bootstrap_token = $env:WORKBENCH_BOOTSTRAP_TOKEN
} | ConvertTo-Json -Compress
$bytes = [System.Text.Encoding]::UTF8.GetBytes($body)      # PS 5.1 中文/编码保险写法
Invoke-RestMethod -Method Post -Uri "$BASE/api/v1/auth/registrations" -ContentType "application/json" -Body $bytes |
  ConvertTo-Json -Compress
# 期望：201，角色 super_admin、状态 approved、reviewed_by=bootstrap
# 若返回 403「首个管理员需要正确的初始化口令」＝ bootstrap_token 不对（或环境里已有超管）
```

> 判据口径（runbook §1.3 实测）：**403 = 还没有超管**（口令对不对都先看这条）；**201 且 pending = 已经有超管**（流程变成了普通申请）。

### 9.2 超管绑 TOTP（超管属强制 MFA 角色）

```powershell
# ① 先登录看 scope：期望 scope=totp_enrollment（尚未绑定）
$login = @{ phone = "<手机号①>"; password = "<口令>" } | ConvertTo-Json -Compress
$s1 = Invoke-RestMethod -Method Post -Uri "$BASE/api/v1/auth/sessions" -ContentType "application/json" `
  -Body ([System.Text.Encoding]::UTF8.GetBytes($login))
$s1.scope; $s1.expires_in
$env:T1 = $s1.access_token

# ② 取 secret / otpauth_uri，用手机验证器扫码绑定
Invoke-RestMethod -Method Post -Uri "$BASE/api/v1/auth/me/totp" -Headers @{ Authorization = "Bearer $($env:T1)" } |
  ConvertTo-Json -Compress

# ③ 用验证器**当前**6 位码确认（有效期 300 秒，尽快）
$confirm = @{ totp_code = "<6 位码>" } | ConvertTo-Json -Compress
Invoke-RestMethod -Method Post -Uri "$BASE/api/v1/auth/me/totp/confirmation" `
  -Headers @{ Authorization = "Bearer $($env:T1)" } -ContentType "application/json" `
  -Body ([System.Text.Encoding]::UTF8.GetBytes($confirm))
# 期望：{"status":"confirmed"}

# ④ 等验证器翻到**下一个**步长码（≤30 秒）再登录：期望 scope=full
$login2 = @{ phone = "<手机号①>"; password = "<口令>"; totp_code = "<新码>" } | ConvertTo-Json -Compress
$s2 = Invoke-RestMethod -Method Post -Uri "$BASE/api/v1/auth/sessions" -ContentType "application/json" `
  -Body ([System.Text.Encoding]::UTF8.GetBytes($login2))
$s2.scope    # 期望 full
$env:TOKEN = $s2.access_token
```

> **两个坑（本机实测）**：① 第 ③ 步用过的码**已被消费**，同一步长拿它登录会 `401`「手机号或密码不正确」——**不是口令错**，等下一个码即可；② 这个 `401` 与真口令错一样**计入失败限流**（默认 5 次 / 5 分钟 ⇒ 锁 900 秒），**不要反复重试**。

### 9.3 建只读库账号 `workbench_ro`（runbook §1.1 三步）

```powershell
$env:PGPASSWORD = $env:WORKBENCH_DB_PASSWORD
psql "postgresql://workbench@$($env:WORKBENCH_STAGING_BIND_IP):5432/workbench" -v ON_ERROR_STOP=1 `
  -c "CREATE ROLE workbench_ro LOGIN PASSWORD '$($env:WORKBENCH_RO_PASSWORD)';" `
  -c "GRANT CONNECT ON DATABASE workbench TO workbench_ro;" `
  -c "GRANT pg_read_all_data TO workbench_ro;"
psql "postgresql://workbench@$($env:WORKBENCH_STAGING_BIND_IP):5432/workbench" `
  -c "SELECT rolname, rolsuper, rolcreatedb, rolcanlogin FROM pg_roles WHERE rolname='workbench_ro';"
# 期望：workbench_ro|f|f|t
```

### 9.4 建探针账号（第二手机号；租户 `tenant-staging-b`、角色 `employee`）

```powershell
# ① 普通注册（不带 bootstrap_token）：期望 201、状态 pending
$reg = @{ phone = "<手机号②>"; password = "<≥10 位口令>"; position = "probe"; full_name = "probe" } | ConvertTo-Json -Compress
Invoke-RestMethod -Method Post -Uri "$BASE/api/v1/auth/registrations" -ContentType "application/json" `
  -Body ([System.Text.Encoding]::UTF8.GetBytes($reg)) | ConvertTo-Json -Compress

# ② 超管列出待审批，取 account_id
(Invoke-RestMethod -Method Get -Uri "$BASE/api/v1/auth/registrations?status=pending" `
  -Headers @{ Authorization = "Bearer $($env:TOKEN)" }).items | ConvertTo-Json -Compress

# ③ 超管审批：指定角色与**第二租户**（role 用 employee：非 MFA 角色，探针/跨租户用）
$appr = @{ role = "employee"; tenant_id = "tenant-staging-b" } | ConvertTo-Json -Compress
Invoke-RestMethod -Method Post -Uri "$BASE/api/v1/auth/registrations/<账号ID>/approval" `
  -Headers @{ Authorization = "Bearer $($env:TOKEN)" } -ContentType "application/json" `
  -Body ([System.Text.Encoding]::UTF8.GetBytes($appr))
# 期望：200；重复审批 409；账号不存在 404

# ④ 探针账号登录验证：期望 200、scope=full、role=employee（employee 不需要 TOTP）
$pl = @{ phone = "<手机号②>"; password = "<口令>" } | ConvertTo-Json -Compress
$s3 = Invoke-RestMethod -Method Post -Uri "$BASE/api/v1/auth/sessions" -ContentType "application/json" `
  -Body ([System.Text.Encoding]::UTF8.GetBytes($pl))
$s3.scope; $s3.role; $s3.tenant_id
```

> 角色枚举（代码事实）：`_SUPPORTED_ROLES = {employee, department_lead, ceo, super_admin, customer_admin}`；`_MFA_ROLES = {super_admin, ceo}`。**探针不用 `ceo`/`super_admin`**（要 TOTP、且并发场景会锁定账号）。第二手机号**一机两用**：既是租户 B 的账号（1.7 跨租户探测），又是 1.8 的专用探针（employee 权限足够建任务）。

**回传**：9.1 返回值（脱敏）、9.2 的 `scope` 两次读数、9.3 属性行、9.4 四步的关键字段（**不贴口令、不贴令牌**）。

---

## 10. Step 7 · 预检四连与只读核验（1.3–1.5；只读）

### 10.1 预检四连

```powershell
. D:\workbench-secrets\load-env.ps1
cd D:\workbench\app
.\.venv-accept\Scripts\python.exe scripts\staging_preflight.py
.\.venv-accept\Scripts\python.exe scripts\runtime_staging_preflight.py
.\.venv-accept\Scripts\python.exe scripts\worker_preflight.py --offline
.\.venv-accept\Scripts\python.exe scripts\commercial_g0_preflight.py
```

四条命令**完整输出**回传（报告只含元数据，不含密钥值）。**判读分档（如实口径，不得为凑全绿填假值）**：

| 段 | 项数 | 本轮预期 |
| --- | --- | --- |
| 基础设施（`staging_preflight` 前 7 项） | 7 | PG/Redis/对象存储/租户/命名空间 5 项 pass；**RAGFlow / AgentScope「测试账号就绪」2 项如实 fail**（未接入，见 §12 D4） |
| 商业化 G0 | 9 | 应全 pass（密钥、迁移清单回填、保留策略、Runtime 版本表已如实登记） |
| 外部 Runtime | 20 | 运行环境/Staging 标识/网络白名单 3 项可 pass；**五类 Runtime 的 17 项按就绪实际情况如实 fail/pass**——未部署的不要声明 |

> ⇒ **1.3 / 1.4 的完整 pass 依赖外部 Runtime 接入**（§14 待拍板）。本轮把通过项照实登记，未通过项进「受限项」，**不粉饰**。

联网版 worker 预检（拿到超管 `full` 令牌后）：

```powershell
$env:WORKBENCH_ACCEPTANCE_BASE_URL = "http://$($env:WORKBENCH_STAGING_BIND_IP):8000"
$env:WORKBENCH_ACCEPTANCE_TOKEN = $env:TOKEN
.\.venv-accept\Scripts\python.exe scripts\worker_preflight.py --allow-insecure-local
```

### 10.2 只读核验（1.5，按 runbook 执行）

按 [`docs/readonly-verification-runbook.md`](readonly-verification-runbook.md) §2 的九条 SQL（用 `workbench_ro` 只读账号 + `SET default_transaction_read_only = on` 双保险）与 §3 的 API 组执行。本机预演已证明「命令一到 staging 即可执行」（2026-09-16，见 checklist 1.5 注记）。

```powershell
$env:WORKBENCH_PSQL_DSN = "postgresql://workbench_ro:$($env:WORKBENCH_RO_PASSWORD)@$($env:WORKBENCH_STAGING_BIND_IP):5432/workbench"
# 然后按 runbook §2 逐条跑（注意：psql 用**不带** +psycopg 的写法）
```

**回传**：runbook §2 每条的输出（按 A–H 标号）+ §3 的响应码与关键字段。

---

## 11. Step 8 ·【授权点 · 待前置】备份与恢复演练（1.6）

> **前置（未定项）**：① 备份介质（**不要与库同盘**——理想是外接盘/另一台机器共享目录；单盘机器退而求其次放独立目录并登记）；② 第三把密钥（Step 3 已生成 `WORKBENCH_ARCHIVE_KEY`，用于**落盘归档加密**——`pg_dump` 不自带加密）；③ 一次维护窗口（真回滚演练需要；本轮「导出 + 隔离库恢复」不改主库数据，但仍按写操作口径走授权）。

```powershell
. D:\workbench-secrets\load-env.ps1
cd D:\workbench\app
$env:WORKBENCH_APPLIED_MIGRATIONS = $env:WORKBENCH_APPLIED_MIGRATIONS   # 已回填，确认非空

# ① 清单核对（dry-run，先跑）
.\.venv-accept\Scripts\python.exe scripts\migration_backup_drill.py --phase list
# 期望：[pass] 迁移清单一致（与仓库 migrations/*.sql 数量一致，2026-09-18 现为 39 项）

# ② 备份命令预演（默认 dry-run，只打印不执行；观察脱敏后的命令）
.\.venv-accept\Scripts\python.exe scripts\migration_backup_drill.py --phase backup --backup-dir D:\workbench-backups

# ③ 真执行导出（--execute 才真跑；需授权）
New-Item -ItemType Directory -Force -Path D:\workbench-backups | Out-Null
.\.venv-accept\Scripts\python.exe scripts\migration_backup_drill.py --phase backup --execute --backup-dir D:\workbench-backups

# ④ 落盘归档加密（pg_dump 不内置加密；用第三把密钥 AES-256 + 加密文件名）
winget install --exact --id 7zip.7zip --accept-source-agreements --accept-package-agreements
& 'C:\Program Files\7-Zip\7z.exe' a -p"$env:WORKBENCH_ARCHIVE_KEY" -mhe=on `
  D:\workbench-backups\workbench-backup.dump.7z D:\workbench-backups\workbench-backup.dump
# ⑤ 删除明文 dump（只留加密件）
Remove-Item D:\workbench-backups\workbench-backup.dump

# ⑥ 隔离恢复库（同实例、不同库；不算「本地」，脚本护栏允许）
psql "postgresql://workbench@$($env:WORKBENCH_STAGING_BIND_IP):5432/workbench" `
  -c "CREATE DATABASE workbench_restore;"
.\.venv-accept\Scripts\python.exe scripts\migration_backup_drill.py --phase restore `
  --execute --backup-dir D:\workbench-backups `
  --restore-dsn "postgresql+psycopg://workbench:$($env:WORKBENCH_DB_PASSWORD)@$($env:WORKBENCH_STAGING_BIND_IP):5432/workbench_restore"

# ⑦ 恢复后核对（脚本的 verify 阶段：健康检查 + 迁移清单一致性）
.\.venv-accept\Scripts\python.exe scripts\migration_backup_drill.py --phase verify `
  --base-url "http://$($env:WORKBENCH_STAGING_BIND_IP):8000" --token $env:TOKEN --allow-local
```

- 恢复后补一条**人工核对**（教你「备份是真的能恢复」）：在 `workbench_restore` 库里查 `SELECT count(*) FROM workbench_schema_migrations;` 期望 34。
- **演练后清理**（经我确认再删）：`DROP DATABASE workbench_restore;` 与 `D:\workbench-backups` 中的中间文件。
- ⚠️ 脚本的 `--phase restore` 口径是「恢复到隔离库 → 前滚到最新 → 清单比对」；**「回退到指定历史版本」不是该脚本能力**（旁证为 10.12 的一次性容器 027 回退），真正的版本回退演练需维护窗口 + 另行授权。

---

## 12. 偏差登记（相对 `docs/infra-input-request.md` 的口径差异，如实登记）

| 编号 | 偏差 | 理由与影响 | 缓解 |
| --- | --- | --- | --- |
| D1 | **I1 主机类型**：索取表写「独立 Linux 主机」，本方案用 **Win10 22H2 台式机 + Docker Desktop/WSL2** | 技术栈全容器化，跨机可达性与预检判据（非本地 host）均成立；代价是 OS 层差异（Win10 22H2 已于 2025-10-14 结束主流支持） | 仅内网暴露 + 防火墙限域（7.4）+ 专用凭据 + 不装无关软件；不承载生产数据 |
| D2 | **地址形态**：`$IP` 为局域网 IPv4，非 DNS 域名 | 预检只要求「非本地 host」，不校验域名 | 后续如需域名/TLS，另起反代方案（本期不做） |
| D3 | **端口暴露**：基础编排 `127.0.0.1` + 本方案**追加** `$IP` 绑定 | 跨机访问必须真实可达；Docker Desktop 的端口代理粒度在个别版本会把绑定落到 `0.0.0.0` | 以 Windows 防火墙（Private + LocalSubnet）收窄；`netstat` 实测若见 `0.0.0.0` 则在此登记 |
| D4 | **外部 Runtime 未接入**：RAGFlow / AgentScope / DeerFlow / Codex Worker / Hermes 的就绪声明**如实留空** | 未部署就是不部署——**不得为凑预检全绿而填 `true`**（红线：不虚报） | 1.3/1.4 的 Runtime 段进「受限项」，待真实接入后补跑；本地三进程若在开发机已有，可评估登记其真实地址（§14） |
| D5 | **进程守护**：Docker Desktop 随登录自启 + 容器 `restart: unless-stopped`，无 systemd 级守护 | Windows 单机形态固有 | 重启后自查 `docker compose ps`；如长期无人值守，另配计划任务（本期不做） |
| D6 | **embedding（E1）落点：已定案（A：台式机自包含，2026-09-16）** | 新增 `docker-compose.embedding.yml`（TEI CPU 镜像钉 digest + 模型只读挂载 + 仅宿主回环；模型预下载 ≈1.2 GB）；生产模式下 app 缺 `WORKBENCH_EMBEDDING_BASE_URL` 会**启动即失败**（fail-closed，`app/bootstrap.py`），compose 亦以 `:?required` 预拦 | 摘要与契约兼容性已核（开发机只读解析取证）；**真机起栈未验证**——随 Step 4 取证 |
| D7 | **备份介质（I11）未定** | 演练前必须定「写哪里 + 第三把密钥怎么存」 | 见 §14；建议外接盘或开发机共享目录，不与库同盘 |
| D8 | **Docker Desktop 许可** | 商业规模（>250 人或 >$10M 年收入）需付费订阅 | 待核自评（§14） |

---

## 13. I1–I14 索取表映射（本方案如何满足）

| 项 | 本方案落点 | 状态 |
| --- | --- | --- |
| I1 独立主机 | 台式机（D1 偏差） | 待执行 |
| I2 PG 客户端 | Step 1.5（winget 装 16 + 停服务） | 待执行 |
| I3 独立 PG 实例 | Step 4（pgvector 容器，`$IP:5432`） | 待执行 |
| I4 pgvector | 镜像自带；Step 4「可安装」→ Step 5「已启用（有一行）」两处读数 | 待执行 |
| I5 只读账号 | Step 6.3（runbook §1.1 三步） | 待执行 |
| I6 迁移清单 | Step 5.4 从 `workbench_schema_migrations` 读出 → 回填 `WORKBENCH_APPLIED_MIGRATIONS` | 待执行 |
| I7 独立 Redis | Step 4（valkey 容器，`$IP:6379`） | 待执行 |
| I8 独立对象存储 | Step 4（seaweedfs，`$IP:9000` + 命名空间 `staging-customer-a`） | 待执行 |
| I9 双密钥注入 | Step 3（AUTH / BACKUP 两把，≥32 且互不相同）；本方案另加 1 把归档密钥（第三把） | 待执行 |
| I10 租户 + 超管 | Step 6.1/6.2（bootstrap + TOTP，租户 `tenant-staging-a`） | 待执行 |
| I11 备份介质 + 密钥 + 窗口 | Step 8 前置（§14 未定） | **待拍板** |
| I12 探针账号 | Step 6.4（第二手机号，`employee`，租户 B） | 待执行 |
| I13 死信渠道 | 本轮**不接**（如实；死信仍可查可重放，1.10 判据相应跳过通知项） | 待确认 |
| I14 变量对照单 | Step 3 的 `staging.env`（含两处 Step 5 回填）+ Step 7 预检读数 | 待执行 |

---

## 14. 待拍板项（按阻塞顺序）

| # | 事项 | 说明 | 阻塞 |
| --- | --- | --- | --- |
| E1 | **embedding 服务落点** | **已定案（2026-09-16）**：**方案 A——台式机自包含**。TEI CPU 镜像（钉 digest）加载 Qwen3-Embedding-0.6B，模型 Step 2 预下载后只读挂载；契约 `POST {base}/v1/embeddings`（1024 维）+ `GET {base}/health`；app 以服务名 `http://embedding:8080` 寻址（仅容器网络 + 宿主回环，**禁公网**） | **已解除**（编排与步骤已补：§5 模型预下载、§6 变量、§7 Step 4） |
| U6 | **手机号分配** | 手机号① 超管（租户 A）；手机号② 探针 + 租户 B（一机两用）。若你希望「探针」与「租户 B 账号」分开，需要第三个号 | Step 6 |
| I11 | **备份介质 + 第三把密钥保管 + 维护窗口** | 介质建议外接盘/开发机共享目录（不与库同盘）；`WORKBENCH_ARCHIVE_KEY` 已生成在 `staging.env`，**需另行抄存**（丢了备份就解不开） | Step 8 |
| U5/I13 | **死信通知渠道** | 默认本轮不接（如实登记） | 1.10 通知项 |
| — | **外部 Runtime 就绪实况** | 请在**开发机**跑 `docker ps --format "{{.Names}}`t{{.Image}}`t{{.Ports}}"` 回传，我据此判断五类 Runtime（尤其 RAGFlow/AgentScope/三本地进程）有没有真实可用实例、地址与版本能不能如实登记 | 1.3/1.4 的 Runtime 段 |
| — | **地址稳定性** | `$IP` 建议在路由器做 **DHCP 保留**（比手工静态更稳）；也可设静态 | 全程 |
| — | **Docker Desktop 许可** | 商业规模自评；>250 人或 >$10M 年收入需付费订阅 | 不阻塞（先登记） |

---

## 15. 常见失败判读表（把原始报错贴回来即可，别自行改配置）

| 现象 | 最可能原因 | 处理方向 |
| --- | --- | --- |
| `docker version` 连不上 Server | Docker Desktop 未启动 / WSL2 未就绪 | 启动 Docker Desktop，等鲸鱼变绿；`wsl --status` 确认默认版本 2 |
| `psql` 连接被拒 / 超时 | 端口未发布 / 防火墙未放行 / `$IP` 填错 | 回 Step 7.5 看绑定面；确认防火墙规则（7.4）与 `$IP` |
| 端口 5432 被占 | PostgreSQL Windows 服务没停 | 回 Step 1.5 的 `Stop-Service` + `Set-Service -StartupType Disabled` |
| `pg_dump: 无法识别的命令` | PG 客户端 bin 不在 PATH | Step 1.5 的 `$env:Path += …` |
| compose 报 `set WORKBENCH_STAGING_BIND_IP to …` | env 文件没载入 / 缺该变量 | 先 `. D:\workbench-secrets\load-env.ps1`，再确认 6.5 自查 |
| compose 报 `WORKBENCH_EMBEDDING_BASE_URL … required` 或 `WORKBENCH_EMBEDDING_MODEL_DIR … required` | `staging.env` 缺值 / 没载入 env 文件 | 先 `. D:\workbench-secrets\load-env.ps1`，再按 6.5 自查两个变量（这是 fail-closed 的设计行为） |
| `ghcr.io` 拉取 embedding 镜像失败 | 网络 / 镜像源不可达 | 贴原始报错，**不要**自行改镜像源；确需其他源则按 §12 登记偏差 |
| `logs embedding --tail 80` 报启动或模型加载失败 | 模型目录未预下载 / 挂载路径不符 / pooling 解析异常 | 把原始日志一个字不改贴回；先核对 Step 2 模型目录与 §1.3 `$MODEL_DIR` |
| embedding `/health` 非 200 或向量维度 ≠1024 | 模型仍在加载（等 30–60 秒）/ 加载异常 | 先等待重试；仍不对就**停手**贴回原始输出判读，不要改 compose 参数 |
| compose 报 `service app has neither an image nor a build context` | 只给了 base + override，漏了 `-f docker-compose.app.yml` | 用本文固定四 `-f` 组合 |
| app 容器反复重启 | 迁移失败 / 密钥缺失 / embedding 地址不可达 | `logs app --tail 80` 把原始报错贴回 |
| 本机 health 200、跨机不通 | 防火墙 / `$IP` | 7.4 + 7.5 |
| TOTP 确认后立刻登录 `401` | 用了**已被消费**的同一步长码（不是口令错；且计失败次数） | 等验证器翻到下一个码（≤30 秒）再登录；不要连试 |
| 探针首跑 `login_throttle` 报 `{401:8}` | 并发请求在锁定生效前同时通过「未锁定」检查（**已知行为**） | 紧接着再跑一次即 `{429:8}`；**不要改代码或调配置** |
| SeaweedFS 容器起不来 | `s3.json` 凭据含非法字符（`"` 或 `\`） | 用 Step 6.2 生成的字符集（数字+大小写字母），不要手改 |
| `--phase list` 报「迁移清单不一致」 | `WORKBENCH_APPLIED_MIGRATIONS` 未回填 / 与库内不一致 | 回 Step 5.4 重新回填 |
| 预检 Runtime 段大量 fail | 外部 Runtime 未接入（**预期内**） | 不做假声明；按 §14 补齐真实信息后可复跑 |

---

## 附：执行记录表（每步执行后由我登记）

| 步 | 执行日期 | 结果 | 回传摘要 | 判读 |
| --- | --- | --- | --- | --- |
| Step 0 | | | | |
| Step 1 | | | | |
| Step 2 | | | | |
| Step 3 | | | | |
| Step 4 | | | | |
| Step 5 | | | | |
| Step 6 | | | | |
| Step 7 | | | | |
| Step 8 | | | | |