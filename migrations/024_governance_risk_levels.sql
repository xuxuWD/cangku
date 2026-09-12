-- 024：治理风险档位校正（D18）
--
-- 背景：参照产品完整源码研读查出，其 `full_auto` **仍然要审批 `critical` 风险**
--   （`needs_approval = risk >= threshold`，三档阈值 full_auto→critical），
--   而本项目 P1a 的 `risk_threshold` 只有 3 档且 `full_auto` 完全免批无兜底。
--
-- 本迁移只做数据库层的档位扩展；「critical 任何自治等级都不得豁免」的判定在
--   应用层写死（`app/workforce/models.py::needs_approval`），并有反假测试守护。

-- 023 里该列是用列级 `CHECK` 建的，PG 会自动命名为 <表名>_<列名>_check。
ALTER TABLE workbench_digital_employees
    DROP CONSTRAINT IF EXISTS workbench_digital_employees_risk_threshold_check;

ALTER TABLE workbench_digital_employees
    ADD CONSTRAINT workbench_digital_employees_risk_threshold_check
    CHECK (risk_threshold IN ('low', 'medium', 'high', 'critical'));
