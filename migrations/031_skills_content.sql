-- 031_skills_content.sql
-- P4 技能层 M5 裁决（2026-09-15）：技能包正文**库内落库**。
-- 依据：docs/superpowers/specs/2026-09-15-skill-layer-p4-design.md §4 M5（已裁决）。
--
-- 约定：
--   * 030 已上线不可改，正文列走**新增迁移**（结构变更走 migration，宪法）。
--   * `content_body` 为技能包正文（TEXT）；体积上限由**服务端**校验
--     （`WORKBENCH_SKILL_CONTENT_MAX_BYTES`，默认 64 KiB），DB 不做长度约束（TEXT 即足够）。
--   * `content_sha256`（030 已有）为正文指纹：提交时服务端可选对 `package_bytes` 计算，
--     若提供 `content_body` 则以其 UTF-8 字节计算指纹，两者必须一致（防篡改/防错配）。

ALTER TABLE workbench_skills
    ADD COLUMN IF NOT EXISTS content_body TEXT NOT NULL DEFAULT '';