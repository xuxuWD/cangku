# Harness POC 许可证与供应链清单

| 项目 | 当前定位 | 必查项 |
|---|---|---|
| DeerFlow | 通用长任务候选 | MIT 文本、依赖 SBOM、固定版本、容器镜像 |
| Codex App Server/Worker | FDE 执行候选 | Apache-2.0、Rust 依赖、沙箱和商标声明 |
| Hermes | 成长能力参考/隔离 Worker | MIT 文本、模型/工具依赖、数据边界 |
| DeepSeek Harness | 实验对照 | MIT 文本、开发预览破坏性变更 |
| OpenClaw | 待审查 | GitHub API 许可证状态、依赖和第三方声明 |
| EvoFlow | 不作为商业底座 | Evovex AI Non-Commercial License，禁止未经授权商业使用 |

每次升级都要重新生成 SBOM、扫描漏洞、核对许可证和回滚版本。任何无法完成审查的依赖不得进入生产路径。
