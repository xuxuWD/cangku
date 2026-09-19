# B1 数据导出走查（2026-09-18T18:56:42.202Z）

结论：42/42 通过

- [x] 前置：商业化租户已登记且导出列表可读 — usage=200 list=200 total=0
- [x] 页面：用量账本区块仍在（关联功能未被牵连）
- [x] 页面：数据导出区块渲染
- [x] 页面：申请导出入口可用
- [x] 页面：空/列表态与走查前包数一致（走查前 0 个）
- [x] 申请后：进入等待态（不本地插行）
- [x] 生成：页面确认「导出包已生成」（认服务端作业状态）
- [x] 生成：服务端确实多了一个导出包（+1） — total=1
- [x] 生成：新包落在列表首位（生成时间倒序） — export-0766ab7ddf00
- [x] 生成：列表不给载荷（仅元数据） — package_id,tenant_id,job_id,created_at,expires_at
- [x] 下载：给出下载文件名（按包号命名） — 租户数据导出-export-0766ab7ddf00.json
- [x] 下载：载荷是本租户的（tenant_id 一致） — demo-tenant
- [x] 下载：15 类类别齐备（未接线的以空数组如实呈现） — 15
- [x] 下载：已接线类别不再出现在 unimplemented 里 — approvals,growth_proposals,knowledge_references,knowledge_versions
- [x] 下载：未接线类别如实标注（剩余 4 类无实体） — 剩余 4 项：approvals,growth_proposals,knowledge_references,knowledge_versions
- [x] 下载：岗位行是真取到的（含走查种子） — [{"role_key":"walk-role","name":"走查岗位","description":"B-2 走查种子","status":"active","created_by":"admin","created_at":"2026-09-18T18:56:12.016329+00:00","updated_at":"2026-09-18T18:56:12.016331+00:00"}]
- [x] 下载：数字员工行是真取到的 — [{"agent_key":"walk-agent","role_key":"walk-role","name":"走查数字员工","description":"","status":"active","created_by":"admin","created_at":"2026-09-18T18:56:12.016346+00:00","updated_at":"2026-09-18T18:56:12.016346+00:00"}]
- [x] 下载：知识文档行是真取到的 — [{"document_id":"walk-doc","title":"走查文档","owner_id":"admin","status":"draft","version":"v1","source_key":"walk","registered_by":"admin","last_reviewed_at":null,"review_due_at":null,"created_at":"2026-09-18T18:56:12.016359+00:00","updated_at":"2026-09-18T18:56:12.016359+00:00"}]
- [x] 下载：运行行是真取到的 — [{"run_id":"walk-run","task_id":"walk-task","proposal_id":null,"runtime_key":"mock","status":"completed","step_count":0,"completed_step_count":0,"tool_calls":0,"successful_tools":0,"knowledge_hits":0,"latency_ms":0,"started_at":"2026-09-19T08:00:00+00:00","finished_at":null,"finish_reason":null}]
- [x] 下载：审计行是真取到的 — [{"record_id":"audit-a64f53488d29","action":"account.login.succeeded","actor_id":"admin","target_type":"account","target_id":"walk-account","phone_masked":null,"detail":{},"occurred_at":"2026-09-18T18:56:12.016403+00:00"}]
- [x] 下载：任务行是真取到的（B-2b） — [{"task_id":"walk-task","project_id":"walk-project","created_by":"admin","employee_key":"content-writer","title":"走查任务","risk_level":"low","budget":5,"status":"queued"}]
- [x] 下载：用户行是真取到的且手机号已掩码（B-2b） — [{"account_id":"acct-234f66285f37","phone_masked":"137****0001","position":"内容运营","full_name":"走查账号","email":null,"role":"employee","status":"approved","requested_at":"2026-09-18T18:56:12.016664+00:00","reviewed_at":"2026-09-18T18:56:12.016672+00:00","reviewed_by":"admin"}]
- [x] 下载：用量行是真取到的（B-2b） — [{"id":"usage-b3cb44bd0398","units":7,"cost_cents":70,"reversal_of":null,"occurred_at":"2026-09-18T18:56:12.016687+00:00"}]
- [x] 下载：用户行不含口令/令牌列（阴性核查）
- [x] 下载：产物行是真取到的（B-2c） — [{"run_id":"walk-run","artifact_id":"895314be1fde498b8cbcb03ed0e0d10d","virtual_path":"/workspace/walk.txt","change_kind":"created","bytes":16,"sha256":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","created_at":"2026-09-18T18:56:12.016710+00:00","expires_at":"2026-10-18T18:56:12.016710+00:00"}]
- [x] 下载：步骤行是真取到的（B-2c，两个计划步骤各一行） — [{"run_id":"walk-run","step_id":"s1","kind":"read","tool":"knowledge.search","requires_approval":false,"completed":false},{"run_id":"walk-run","step_id":"s2","kind":"write","tool":"file.write","requires_approval":true,"completed":false}]
- [x] 下载：他租户的种子一行都没进来（真实文件里的租户隔离）
- [x] 下载：三类如实标注字段齐备（无截断 / 无读取失败） — []{}
- [x] 下载：脱敏声明随包（密码/令牌等一律不导出） — ["密码","Cookie","验证码","令牌","原始 API 密钥","客户原文"]
- [x] 下载：数据面无敏感词元（阴性核查） — 干净
- [x] 页面：下载后给出「已开始下载」如实说明
- [x] 页面：载荷内容不进页面（不做无意义回显）
- [x] 刷新：导出包仍在列表（权威态回流）
- [x] 刷新：列表总数与页面标注一致
- [x] 关联点检：用量与费用仍是服务端数值（非占位符） — 用量账本 | demo-tenant | 用量口径 | 账本记录的原始单位，页面不做业务含义解释。 | 费用口径 | 账本以整数分记账；发生过冲正时累计可能为负。
- [x] 歪路①：普通员工查导出列表 ⇒ 403 — 403
- [x] 歪路①：普通员工取回导出包 ⇒ 403 — 403
- [x] 歪路②：不存在的包号 ⇒ 404 — 404
- [x] 歪路③：limit=0 ⇒ 422 — 422
- [x] 干净：页面零控制台错误
- [x] 干净：页面零未捕获异常
- [x] 干净：页面零 4xx/5xx 响应

## 证据
- 下载包（脱敏 JSON）：docs\screenshots\ui-v2-b1-export\package.json
- 截图：01-before-request / 02-waiting / 03-generated / 04-downloaded