# 安全政策（Security Policy）

> **当前状态（如实）**：本仓库为**内部项目仓库**（`github.com/xuxuWD/cangku`），
> **尚未建立正式的漏洞响应时限承诺**（例如"24 小时内响应"）。
> 本文件描述**现行做法与边界**；**不构成任何未落地的服务承诺**。
> 若本仓库将来转为公开项目，本文件须**重写并经评审**。

## 1. 报告漏洞

**首选渠道**：本仓库的 GitHub **私有漏洞报告**（仓库 `Security` 页签 → `Report a vulnerability`）。

**若该入口不可用**：直接联系本仓库负责人（内部渠道），**不要在公开 issue 中粘贴利用细节**。

**报告请包含**（能提供多少就提供多少）：

- 受影响的**端点 / 文件 / 组件**与版本（或提交号）；
- **复现步骤**（最小可复现集）与观察到的结果；
- 影响面判断（是否能跨租户读取、是否能越权写入、是否需要已登录身份）；
- 你**已经验证过**的部分与**尚未验证**的部分（请分开写，不要合并陈述）。

## 2. 明确的处理边界

- 我方**不承诺**未实际建立的响应时限、修复时限或致谢安排。
- 我方**不承诺**对未经证实的效果（例如"你的报告一定会被采纳"）做保证。
- 涉及**生产数据**的测试**不要直接在生产环境执行**；需要生产数据时只取**最小一份并脱敏**。
- 我方设备与凭据不向外部提供；**不接受**"先给环境再判断"的报告方式。

## 3. 仓储侧安全约定（与代码库现状一致）

| 约定 | 现状 | 依据 |
| --- | --- | --- |
| `.env`、密钥、Cookie、浏览器会话、客户原文、临时媒体**不入库** | 已由 `.gitignore` 排除（`.env`、`.env.*`、`*.key`、`tmp/`），仅保留 `*.example` 模板 | [.gitignore](file:///d:/徐徐AI学习/公司工作台/.gitignore) |
| 密钥**只从环境注入**；进过仓库的密钥**必须轮换**（不是删掉那一行） | 容器编排用 `:?` 强制要求密钥；`.dockerignore` 排除全部环境文件 | [README.md](file:///d:/徐徐AI学习/公司工作台/README.md#L52-L57) |
| 生产**关闭调试**、配置外置、数据库不对公网开放 | 见交付门禁与私有部署手册 | [docs/delivery-gates.md](file:///d:/徐徐AI学习/公司工作台/docs/delivery-gates.md)、[docs/private-deployment-runbook.md](file:///d:/徐徐AI学习/公司工作台/docs/private-deployment-runbook.md) |
| 密钥**扫描基线** | `.gitleaks.toml` **已提供，但尚未实跑**（工具未安装、CI 未接入）⇒ **不得读成"密钥扫描已上线"** | [.gitleaks.toml](file:///d:/徐徐AI学习/公司工作台/.gitleaks.toml) |

## 4. 攻击面自查记录（既有，可复核）

- 攻击面报告：[docs/security-attack-surface-report.md](file:///d:/徐徐AI学习/公司工作台/docs/security-attack-surface-report.md)
- 复测手册：[docs/attack-surface-retest-runbook.md](file:///d:/徐徐AI学习/公司工作台/docs/attack-surface-retest-runbook.md)
- 沙箱边界裁决：[docs/sandbox-boundary-decision.md](file:///d:/徐徐AI学习/公司工作台/docs/sandbox-boundary-decision.md)

> **诚实声明**：上述报告**不等于**持续安全保证；其中的"未验证"项以各文自身标注为准。