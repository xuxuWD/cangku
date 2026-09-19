# 租户 schema 模板链（`migrations/tenant_template/`）

> Schema 级多租户改造 · **S0 准备阶段**生成物。方案见 `docs/contracts/schema-per-tenant-plan.md`。

## 这条链是什么

租户 schema 的**基线 DDL**：每新建一个租户 schema，就在该 schema 内按序应用本目录 SQL，得到与
`public` 一致的 51 张租户表（表/列/索引/约束四项集合一致，已空库实测通过）。

- `classification.json` —— **权威**表归属清单：`tenant_schema`(A 51) / `platform_tenant_scoped`(B 4) / `platform_core`(C 6)
- `0001_tenant_baseline.sql` —— 租户 schema 基线 DDL（**自动生成，勿手改**）

## 双链规则（今后结构变更必守）

平台链 `migrations/*.sql`（44 个历史文件，不改写）与**租户模板链**并存：

- 任何结构变更，凡属于 A 组表的 DDL，**两条链都要改**（平台链写新迁移 + 本模板重新生成）；
- CI 守护：`0001_tenant_baseline.sql` 的 `CREATE TABLE` 集合必须 == `classification.json` 的 `tenant_schema`，判定口径即 `py scripts/tenant_schema.py verify`。

## `${PLATFORM_SCHEMA}` 占位符约定

模板内指向 B/C 组平台表的 `REFERENCES` 一律写成 `${PLATFORM_SCHEMA}.<表名>`（当前 4 处，均指向
`workbench_tenants`）；执行方应用模板时替换成平台 schema 的真实名字（当前为 `public`）。其余对象
**不带 schema 限定**（裸名），靠 `SET search_path` 解析；**序列随表入租户 schema**（`CREATE SEQUENCE`
/ `OWNED BY` / 列的 `nextval` 同样去 `public.`，当前 2 个序列 + 2 条 `SET DEFAULT`），保证自增行为一致。
扩展类型与其 opclass（如 `public.vector`）不在改写范围，仍保留 `public.`。`verify --apply` 的比对含
`column_default`，比对前按上述规则归一化 schema 前缀。

## 生成而非手写

```powershell
py scripts/tenant_schema.py build-template   # 重新生成 0001_tenant_baseline.sql（先改脚本再生成，勿手改产物）
py scripts/tenant_schema.py verify           # 校验分类清单与实测库一致、模板覆盖 == A 组
py scripts/tenant_schema.py verify --apply   # 追加「空库试跑」：临时 schema 应用模板并与 public 比对，跑完清理
py scripts/tenant_schema.py inventory        # 巡检：各 schema 表数 + 本项目 schema（t_%/platform）逐表行数
```

## S0 期决策

模板保持**纯 DDL、不做 `IF NOT EXISTS` 幂等化**——生成物与 `pg_dump` 天然兼容；幂等性由 S1 的「**单事务应用 + 版本台账** `workbench_tenant_schema_versions`」保证，故勿给语句加幂等包装。

## Provenance

- 源库：`wb-test-postgres-1` / `workbench_test` / `public`（PG 16.15）；生成器 `scripts/tenant_schema.py/1.1.0`，命令与日期见 SQL 文件头。
- 未覆盖：触发器/规则、函数、视图、自定义类型与域、扩展对象本身、COMMENT、GRANT/所有者/表空间/存储参数、RLS、分区继承；序列自身的属性（START/INCREMENT/CACHE）与归属亦未跨 schema 比对。