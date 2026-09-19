# 岗位模板表（唯一权威）

> 状态：**草案 v1 · 2026-09-19**（第 0 轮交付物）。依据：《PRD》§5.2 OP-02 / §5.4 DE-01、
> 《启动准备清单》§九（"岗位模板表"属最小可开始 5 项之一）、仓库实测现状。
> **岗位模板 = 能力包**：选岗位即自动继承（Skill / MCP / 知识库范围 / 记忆策略 / 自治档），
> 实现与本文冲突时以本文为准；变更必须回写本文件。配套：`permission-matrix.md`、`knowledge-acl.md`。

## 1. 能力包字段（模板 Schema，定死）

| 字段 | 含义 | 取值来源 |
| --- | --- | --- |
| `role_key` | 岗位键（唯一） | 既有 `workbench_job_roles.role_key` |
| `mission` | 一句话使命（给用户看，不是给机器看） | 本文 §2 |
| `skills[]` | 默认绑定的 Skill（`skill_key@版本`） | 既有技能层（SKILL.md 标准，白名单 + 人工复核） |
| `tools[]` | 默认工具 / MCP 面（白名单，非黑名单） | 既有工具目录 + （待建）MCP 注册中心 |
| `knowledge_scopes[]` | 知识库范围（**库级**）；库内**分级**另由 `knowledge-acl.md` 管 | 既有知识访问绑定（角色/员工 ↔ 知识库） |
| `memory_policy` | 记忆策略：`scope` 上限（user / role / project / organization）+ 允许写入的类别 | 既有记忆层（`owner_kind`/`scope` 枚举） |
| `autonomy_level` | 自治档：`approval_for_all` / `approval_for_risky` / `full_auto` | 既有枚举（迁移 023） |
| `budget_cents` | 单任务预算上限（整数分，非浮点） | 既有任务域口径 |
| `org_ref`（**预留位，本期不填**） | 组织/部门引用（将来对齐身份源组织树时使用） | 已裁决 ADR-0004：暂不引入组织实体、**留扩展位** |

**硬约束**：模板**只授予、不放大**——模板能力必须 ⊆ 使用者权限（见 `permission-matrix.md` §2.3）。

## 2. 首批 6 个岗位模板（种子数据基线）

| 岗位 | 使命 | 关键 Skill（默认绑定） | 工具 / MCP 面 | 知识库范围 | 自治档 | 必须人工确认 |
| --- | --- | --- | --- | --- | --- | --- |
| `sales`（销售） | 帮销售把客户线索变成可跟进的商机 | `crm.lead_intake`、`crm.quote_draft`、`content.outreach_draft` | CRM 读写（受限）、文档生成、**无出网** | 产品资料（内部）、报价规则（机密） | `approval_for_risky` | 对外报价、折让、合同条款 |
| `hr`（人事） | 帮 HR 处理招聘与员工事务的文书工作 | `hr.jd_draft`、`hr.interview_summary`、`doc.extract` | 文档解析、表格处理 | 人事制度（内部）、员工手册（内部） | `approval_for_all` | 一切涉及**员工个人信息**的输出 |
| `rd`（研发） | 帮研发做需求拆解、代码检视与文档 | `rd.repo_inspect`、`rd.spec_draft`、`rd.changelog` | 只读检视集（`ls/cat/head/tail/wc` 等）、沙箱执行 | 技术文档（内部）、接口契约（机密） | `approval_for_risky` | 任何写操作、依赖升级、出网 |
| `finance`（财务） | 帮财务做对账口径核对与报表说明 | `fin.reconcile_hint`、`fin.report_explain`、`doc.extract` | 表格处理（**只读**） | 财务制度（机密）、历史报表（绝密） | `approval_for_all` | 金额结论、对外披露、导出 |
| `ops`（运营） | 帮运营做内容生产与发布准备 | `content.topic_plan`、`content.draft`、`content.review` | 内容工具、图片处理（**无自动发布**） | 运营手册（内部）、品牌素材（内部） | `approval_for_risky` | 对外发布、对外文案定稿 |
| `admin`（行政） | 帮行政处理会议与流程文书 | `office.meeting_minutes`、`office.schedule_hint`、`doc.extract` | 文档解析、日程（只读） | 行政制度（内部） | `approval_for_risky` | 对外通知、涉及他人日程的变更 |

> 说明：Skill 键为**建议命名**，落地时以技能层实际注册的 `skill_key@version` 为准；
> MCP 面在 MCP 注册中心建成前，一律走既有工具执行闸门（九步闸门 + 逐项授权）。

## 3. 数据形态与落地路径（本轮只定契约，不定 schema）

- **现状**：`workbench_job_roles`（岗位目录）+ `workbench_digital_employees`（数字员工，`role_key` 外键）**均无模板列/模板种子** ⇒ 模板无处声明。
- **建议形态**（待 `adr.md` 签字后实施）：
  1. 模板作为**受控种子数据**入库（单表 `role_templates` 或 `job_roles` 增 `template_version` + JSONB `capability_pack`），随迁移落库、可重复初始化；
  2. **创建数字员工时**：读模板 → 生成 `skill_bindings` / 知识绑定 / 记忆策略 / 自治档 → 落 `digital_employees`；
  3. 模板变更**不回溯**已创建员工（避免"悄悄提权"），改为显式"升级模板"动作并写审计。
- **禁止**：模板里写死租户 ID / 用户 ID / 密钥；模板只存能力引用（键 + 版本），不存正文。

## 3.5 岗位合同六要素与审批策略（补充口径）

模板不只是"能力清单"，还应表达为一份**岗位合同**（沿用生态既有范式）：

`职责（mission）· 管辖范围（工作区/项目）· 上班频率/触发方式 · 审批策略 · 人格与表达（SOUL）· 工具与技能白名单（最小权限）`

其中**审批策略**按"自治档 × 任务风险等级"量化，示例：

| 自治档 \ 风险 | low | medium | high / critical |
| --- | --- | --- | --- |
| `approval_for_all`（谨慎） | 需人闸 | 需人闸 | 需人闸（且双人） |
| `approval_for_risky`（平衡，**默认**） | 自动 | 需人闸 | 需人闸（且双人） |
| `full_auto`（全自动） | 自动 | 自动 | **仍需人闸**（模板不得突破） |

> 说明：`full_auto` 也**不能**越过 `permission-matrix.md` §4 的高风险清单；"上班频率/触发方式"含定时、事件触发与手动发起三类。
> 来源（**已逐字复核 2026-09-19**）：`C:\Users\浮生\.evoflow\knowledge\vaults\evoflow-user-guide\explanation\smart-employees.md`
> —— 原文首句即「智能体员工 = 把已有『智能体』编成**岗位合同**——规定职责、工作文件夹、上班频率与审批策略」，
> 与本文六要素同口径；其「**审批策略 × 任务风险** 达到阈值 ⇒ 挂审批」亦印证本节的量化表。
> **两条新发现的边界（登记，不翻案）**：
> ① 该范式里「**正式交工的合法目标受组织树约束**」（只能派给直属下级、不能跳级/同级）⇒ 与 ADR-0004「暂不引入组织」存在张力：
>    第一期并入的 **Agent Teams（DE-08）** 在多员工协作时，**派发/交工的"能派给谁"规则**需要显式定义（本平台只能用"同租户 + 权限交集"表达）——接线轮必须正面对齐，不得默认放开。
> ② 该范式含「**组织树只决定交工合法目标、不自动派活**」的语义（本条一并登记，供第一期协作规则参考）。

## 4. 验收（可验证语句）

1. 选 `sales` 创建数字员工后，其 Skill 绑定、知识库范围、自治档与模板**逐字段相等**（用查询比对，不看界面文字）。
2. 用 `employee` 角色创建数字员工后，其可用能力 ⊆ 该员工自身权限（构造"模板给了但本人没有"的用例 ⇒ 必须被交集裁掉）。
3. 模板变更后，**已创建的员工能力不变**（无回溯），且"升级模板"动作写审计。
4. 任一模板的 `autonomy_level = approval_for_all/full_auto` 时，高风险清单里的动作仍**不可绕过**人工确认（模板不得突破 `permission-matrix.md` §4）。
5. **状态保真**：数字员工面板不得把"未配置 / 样本不足 / 未验证"显示为 `0` 或"成功"（沿用生态既有原则：未验证的数据不得以数字或成功态呈现；无数据要显示为"暂无/未验证"）。