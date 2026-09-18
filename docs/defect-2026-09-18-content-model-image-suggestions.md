# 缺陷记录：内容生成接入真实模型后**随机失败**，且错误提示误导

> **性质**：**缺陷记录（已修复 · 已用真实模型端到端验证）**。发现于「把真实模型 Key 配到本系统」的联调过程中。
> **日期**：2026-09-18
> **状态**：**根因已定位 → 按用户裁决（选项 C：提示词 + 解析层）修复 → 单测/反假/全量回归通过 → 真实模型端到端闭环验证通过**。详见 §8。
> **未提交**：改动尚未 commit。

---

## 1. 现象

在 `CONTENT_GENERATION_BACKEND=openai_compatible` + DeepSeek 官方端点的配置下，通过 API 创建内容任务：

- `POST /api/v1/content-tasks` → `201`，但 `status = "failed"`
- 草稿 `summary = "模型生成失败，请检查配置后重新生成。"`
- 草稿 `template_version = "generation-failed"`
- 审计链：`content.created` → `content.generation.started` → **`content.generation.failed`**
- 耗时 3.6–5.8 秒（说明**确实调到了上游**）

**同一份输入、同一套代码，在进程内直接调用生成器却稳定成功。** 这是最迷惑人的地方。

---

## 2. 复现步骤（可照抄）

| 步骤 | 命令 / 动作 | 观察 |
| --- | --- | --- |
| 1 | `.env` 配 `CONTENT_GENERATION_BACKEND=openai_compatible`、`CONTENT_MODEL_BASE_URL=https://api.deepseek.com`、`CONTENT_MODEL_NAME=deepseek-chat`、真实 Key | — |
| 2 | 起服务：`.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8100` | 启动正常 |
| 3 | `POST /api/v1/content-tasks`（带 `topic` + 一条 `sources[].excerpt`，头带 `X-Tenant-Id/X-User-Id/X-User-Role`） | `201`，`status=failed` |

**对照实验（证明不是配置问题）**：
- 用同一个 Key 直接 `curl` DeepSeek 官方接口 → **HTTP 200**，正常返回
- 进程内用**我们自己的** `OpenAICompatibleContentGenerator` 连续跑 5 次 → **5/5 成功**（body 610–816 字）
- 进程内用**我们自己的** `ContentService.create(...)` 跑一次 → **成功**，审计 `content.generation.completed`，`detail={"provider":"openai_compatible","model":"deepseek-chat"}`

⇒ **排除**：Key 无效、网络不通、地址/模型名写错、接线错误。

---

## 3. 根因（已定位）

**上游返回的 `image_suggestions` 是「对象数组」，而我们的解析层硬性要求 `list[str]`。**

诊断输出（临时插桩，已还原）：

```
DEBUG_GEN_DIAG {'title_type': 'str', 'title_len': 19,
                'summary_type': 'str', 'summary_len': 73,
                'body_type': 'str', 'body_len': 883,
                'sug_type': 'list', 'sug_len': 4,
                'sug_first_type': 'dict',
                'sug_head': "[{'position': '文章开头', 'description': '一张对比图：……'}, {'position': '“差异原因是什么”部分', 'description': '……'}]",
                'exc': 'ValueError ValueError()'}
```

- 上游实际返回：`[{"position": "文章开头", "description": "..."}, ...]`
- 我们的校验（[`app/content/openai_compatible.py:121`](../app/content/openai_compatible.py)）：
  `if not isinstance(suggestions, list) or len(suggestions) > 20 or not all(isinstance(item, str) for item in suggestions): raise ValueError`
- 元素是 `dict` ⇒ `isinstance(item, str)` 为假 ⇒ 抛 `ValueError()`（无消息）⇒ 被包成 `ContentGenerationError("模型输出格式无效")`

**为什么"看起来随机"**：`temperature=0.2`，模型对 `image_suggestions` 的元素形态**不稳定** ——
有时返回字符串数组（`["配图1", "配图2"]`，通过校验），有时返回对象数组（含 `position`/`description`，被拒）。
进程内 5 次恰好都拿到字符串，服务端 4 次恰好都拿到对象 —— 于是呈现出"进程内能跑、服务里不能跑"的假象。

**直接诱发因素**：系统提示词（[`app/content/openai_compatible.py:47`](../app/content/openai_compatible.py)）只声明了字段名
`title、summary、body_markdown、image_suggestions`，**没有声明每个字段的类型**，也没有使用
`response_format: {"type": "json_object"}` 约束输出结构。

---

## 4. 影响

| # | 影响 | 级别 |
| --- | --- | --- |
| 1 | **真实模型下内容生成随机失败**，成功率不可预期（取决于模型是否恰好返回字符串数组） | **P1**（核心任务无法稳定完成） |
| 2 | **错误提示误导用户**：界面显示「模型生成失败，请检查配置后重新生成。」—— 但**配置完全正确**。用户会去反复检查 Key、地址、模型名，而真正的原因是输出结构 | **P1**（严重误导） |
| 3 | 失败原因**只落在审计明细**（`detail.reason`），而**接口不返回 detail** ⇒ 用户与运维在界面上都看不到真实原因，只能看代码或加日志 | P2（可运维性） |
| 4 | 回归测试**覆盖不到**：现有测试用 `FakeTransport` 构造固定响应，不会产出对象数组 | P2（测试盲区） |

---

## 5. 为什么此前没被发现

- 单元测试全部基于 `FakeTransport` / `MockContentGenerator`，**响应形态是我们自己写死的**；
- 真实模型联调从未做过（此前的门禁记录里，本项一直是「代码完成但未验收」）；
- **只有把真实 Key 接上去、且真的跑起来，才会暴露** —— 这正是"只跑单测不算验收"的典型例证。

---

## 6. 修复选项（待裁决，我不擅自改）

| 选项 | 做法 | 优点 | 缺点 |
| --- | --- | --- | --- |
| **A** | 只改提示词：明确「`image_suggestions` 是字符串数组」 | 改动最小 | **依赖模型听话**，不保证稳定；换个模型又要重调 |
| **B** | 只改解析层：把 `{"position","description"}` 这类对象**降级转成字符串**（如 `"文章开头：一张对比图…"`），同时继续兼容 `list[str]` | 不依赖模型；改动局部、可测 | 需要定义"对象 → 字符串"的转换规则（含未知字段的兜底） |
| **C** | **A + B 都做**：提示词声明类型**并且**解析层容错（推荐） | 既降低发生概率、又兜住长尾；两层独立可测 | 稍多几行代码 |

**无论选哪个，都建议一并做两件事**（否则缺陷只是被绕过、没有被观测到）：
1. **区分失败原因**：把"上游请求失败"与"输出格式不符"分成两类，界面文案分别给（后者提示"模型返回格式不符，可重试"，而不是"请检查配置"）；
2. **补一条回归测试**：用固定响应构造 `image_suggestions` 为**对象数组**的用例 —— **先红后绿**，并按宪法要求做**反假**（去掉容错后必须变红）。

---

## 7. 未验证 / 边界

| # | 项 |
| --- | --- |
| 1 | 其他字段（`title` / `summary` / `body_markdown`）是否也会出现类型漂移 —— **未做**多轮采样统计 |
| 2 | 换用其他 OpenAI 兼容端点（硅基流动 / 胜算云 / 方舟）时该形态是否一致 —— **未验证** |
| 3 | 失败率的具体数值（需要 N 次采样，本轮仅 4 次服务端失败 / 6 次进程内成功）—— **样本过小，不得据此估算成功率** |
| 4 | 本缺陷对 `regenerations`（重新生成）路径的同样影响 —— 代码路径相同，**推断**同样受影响，但**未实测** |

---

## 8. 修复记录（2026-09-18 · 用户裁决 = 选项 C）

### 8.1 改动清单（4 个文件）

| 文件 | 改动 |
| --- | --- |
| `app/content/generator.py` | 新增两个子类 `ContentGenerationUpstreamError` / `ContentGenerationFormatError`（均继承 `ContentGenerationError`，**既有捕获点不受影响**） |
| `app/content/openai_compatible.py` | ① 提示词声明各字段类型（`image_suggestions` 明确为**字符串数组**）；② 新增 `_image_suggestions()` 归一化：对象数组降级为「位置：描述」，跳过空描述与非字符串/对象元素；③ 格式错误改抛 `ContentGenerationFormatError`、上游错误改抛 `ContentGenerationUpstreamError` |
| `app/content/service.py` | 新增 `_failure_summary()`：按失败类型给不同用户文案（**格式类不再说「请检查配置」**） |
| `tests/test_persistence_contract.py` | `Settings()` → `Settings(_env_file=None)`（见 §8.4，**非本缺陷引入**） |

### 8.2 测试（先红后绿 + 反假）

新增 6 条用例（生成器 5 条 + 服务层 1 条）：
`accepts_object_image_suggestions` / `normalizes_partial_object_image_suggestions` /
`keeps_string_image_suggestions_unchanged`（既有行为回归保护）/ `separates_upstream_and_format_errors` /
`prompt_declares_field_types` / `generation_failure_summary_depends_on_reason`。

- **先红**：只加异常类、不改行为时运行 → **4 条断言级失败**（`accepts_object` / `normalizes_partial` / `separates_errors` / `prompt_declares`）；`keeps_string_...` 按设计本就绿。
- **反假**：把归一化绕回旧的严格校验 ⇒ **重新变红**；还原后恢复绿。

### 8.3 真实模型端到端验证（决定性证据）

修复后重启服务，用**真实 DeepSeek** 跑完整闭环：

| 步骤 | 结果 |
| --- | --- |
| `POST /api/v1/content-tasks` | `status=reviewing`（**不再是 failed**），`revision=1` |
| 草稿 | 标题「远程团队沟通成本高？试试这 3 个方法」；正文 428 字；配图建议 **5 条** |
| 配图建议形态 | `文章开头：一张远程团队成员通过视频会议同步工作的场景图，体现跨地域协作。` ⇒ **正是当初触发失败的对象数组被归一化后的结果** |
| 审计链 | `content.created -> content.generation.started -> content.generation.completed` |
| `POST …/confirmation` | `HTTP 200` |
| `GET …/export.md` | `HTTP 200`，24 行完整 Markdown（标题 / 摘要 / 正文 / 配图建议 / 来源 / 任务号 / 确认时间 / 免责说明） |

**全量回归**：`python -m pytest -q` → **`exit=0`**；`python -m compileall -q app tests` → **`exit=0`**。

### 8.4 附带发现（非本缺陷引入）

**测试套件会读取开发者本地的 `.env`** —— `SettingsConfigDict(env_file=".env")` 且用例里 `Settings()` 未做隔离。
⇒ 只要开发者本地按正常做法配了真实模型，`test_persistence_contract.py::test_build_content_generator_selects_mock_or_openai`
就会**误报失败**。本次以 `Settings(_env_file=None)` 隔离该用例（**断言内容未变**）。
**建议后续**：在测试基座统一隔离 `.env`（如 conftest 层强制 `_env_file=None`），否则每个新接入真实外部依赖的开发者都会踩一次。

### 8.5 本次未做（如实登记）

- 未统计该形态漂移的**实际发生频率**（样本仍小，**不得**据此估算成功率）
- 未验证其他 OpenAI 兼容端点（硅基流动 / 胜算云 / 方舟）是否同样返回对象数组
- **未改接口**：失败原因仍只在审计明细里，API 不返回 ⇒ 原 §4 影响 3 **仍成立**
- **已销账（2026-09-18）**：提交 `ded9ed0`（fix）+ `ff48fe9`（docs）已推送 `origin/main`；CI run **`35260327703` 六 job 全绿**（后端 / 后端真库 / 网页管理台 / 手机伴侣端 / 桌面端 / 沙箱加固与逃逸回归）。

---

## 9. 同源复核与第二处修复（2026-09-18 · 用户指令「再复核一下有没有遗漏的」）

### 9.1 复核发现：三处模型输出解析，范式并不统一

| 维度 | 内容生成 | 规划 `planner/generator.py` | CRM 跟进 `crm/followup.py` |
| --- | --- | --- | --- |
| `response_format: {"type":"json_object"}` | ❌ 原本没有（§8 修复时**也漏了**） | ✅ 有（`:89`） | ✅ 有（`:95`） |
| 元素级异质处理 | 修复前整份拒绝 → §8 后归一化 | ❌ **整份拒绝**（`:126-128`） | ✅ **逐条丢弃 + 记录 drops**（`sanitize_output`） |
| 错误分类（上游 vs 格式） | ✅ §8 已区分 | ❌ 混在 `PlanGenerationError` | ❌ 混在 `FollowupPlanError` |

**结论**：本缺陷**不是孤例**；`planner/generator.py` 有**同源实现**（`if not isinstance(item, dict): raise`），模型一旦在 `steps` 里混入非对象元素即**整份计划被拒**。此前未爆发，仅因 `WORKBENCH_PLANNER_BACKEND` 仍为 `mock`。

**正面发现**：`crm/followup.py::sanitize_output`（**越界条目丢弃并记录，而非整份拒绝**）是本项目**既有的正确范式**，内容生成与规划都应对齐它。

### 9.2 第二处修复（本次）

| 文件 | 改动 |
| --- | --- |
| `app/planner/generator.py` | `_parse` 中非对象元素由 **raise 改为 continue**（逐条丢弃）；全被丢弃时返回空列表，交由下游 `normalize_steps`（`planner/models.py:158`「计划必须包含至少一个步骤」）明确拒绝 —— **不在生成器重复设防** |
| `app/content/openai_compatible.py` | 补上 `response_format: {"type": "json_object"}`（与规划 / CRM 对齐，属"降低发生概率"的第一层） |

### 9.3 验证（先红后绿 + 反假）

新增 3 条用例：
`test_openai_generator_drops_non_object_step_items_instead_of_failing_whole_plan` /
`test_openai_generator_drops_all_invalid_steps_and_downstream_rejects_empty_plan` /
`test_openai_compatible_generator_requests_json_object_response_format`。

- **先红**：实现前 **3 条断言级失败**（2 条报 `模型响应中的步骤必须是对象`、1 条 `KeyError: 'response_format'`）。
- **后绿**：`test_planner_generator.py` + `test_content_openai_compatible.py` + `test_content_service.py` + `test_planner_service.py` + `test_planner_api.py` + `test_planner_models.py` ⇒ **全绿**。
- **反假**：两处实现同时还原 ⇒ **3 条重新变红**；还原后恢复绿。
- **全量回归**：`python -m pytest -q` ⇒ **`exit=0`**；`python -m compileall -q app tests` ⇒ **`exit=0`**。

### 9.4 本次未做（如实登记）

- **未统一错误分类**：`planner` 与 `crm` 仍把"上游失败"与"格式不符"混在同一异常里（内容生成已在 §8 区分）。属**跨模块重构**，未在本轮展开。
- **未系统排查其他"整份硬校验第三方响应"的位置**：本次只覆盖了"解析模型输出"这一类。
- `app/memory/embedding.py`、`app/model_gateway/upstream.py` 未复核。
- **已销账（2026-09-18）**：提交 `ded9ed0` + `ff48fe9` 已推送 `origin/main`；CI run **`35260327703` 六 job 全绿**（含本 §9 的第二处修复）。

---

## 10. 第二处复核（2026-09-18 · 用户再次要求复核）

见 [`audit-coverage-review-2026-09-18.md`](audit-coverage-review-2026-09-18.md) §8：本轮把 §9.4 中"未系统排查其他整份硬校验位置"这一**自认缺口真正做掉**，**又命中 4 处同类缺陷**（RAGFlow 引用 / WeKnora 文档列表 / WeKnora 检索 / Runtime 事件流）。**均未修复**，待裁决。
- **未提交 / 未推送 / CI 未跑**。
