"""配置模板的静态契约：模板必须与实际配置项一一对应，且不得被 .gitignore 静默忽略。

背景：`.env.staging.example` 曾因迁移清单落后于 `migrations/` 而让预检永远 `blocked`；
同类漂移在 SSO 模板上同样会让"看起来配好了"的部署实际缺项。这里用 `Settings` 的
真实字段与别名守护模板，避免模板与实际配置再次脱节。
"""

from pathlib import Path

from app.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
SSO_TEMPLATE = ROOT / ".env.sso.example"
GITIGNORE = ROOT / ".gitignore"


def template_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, _ = stripped.partition("=")
        assert separator == "=", f"模板存在无法解析的行：{stripped}"
        keys.add(key.strip())
    return keys


def declared_env_names(field_name: str) -> set[str]:
    """收集某个配置字段可被识别的全部环境变量名（别名 + WORKBENCH_ 前缀）。"""
    field = Settings.model_fields[field_name]
    names = {f"WORKBENCH_{field_name.upper()}"}
    alias = field.validation_alias
    if alias is not None:
        choices = getattr(alias, "choices", None)
        if choices is None:
            names.add(str(alias))
        else:
            names.update(str(choice) for choice in choices)
    return names


def test_sso_template_covers_every_sso_setting() -> None:
    keys = template_keys(SSO_TEMPLATE)
    sso_fields = [name for name in Settings.model_fields if name.startswith("sso_")]
    assert sso_fields, "Settings 中已无 sso_* 字段，请同步更新本测试"

    missing = [
        name for name in sso_fields if not (declared_env_names(name) & keys)
    ]

    # 判定依据：模板必须覆盖每一个 sso_* 配置项，否则部署方按模板配置仍会缺项。
    assert missing == []


def test_sso_template_states_secret_discipline() -> None:
    content = SSO_TEMPLATE.read_text(encoding="utf-8")

    # 判定依据：必须显式写明密钥由部署密钥系统注入、禁止提交真实值，并给出预检命令。
    assert "部署密钥系统" in content
    assert "禁止" in content and "client_secret" in content
    assert "py scripts/sso_preflight.py" in content
    # IdP 侧交付清单必须在模板内，联调输入才可勾对
    for item in ("issuer", "callback", "email_verified", "PKCE"):
        assert item.lower() in content.lower() or item in content


def test_sso_template_is_not_gitignored() -> None:
    entries = {
        line.strip()
        for line in GITIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }

    # 判定依据：`.env.*` 默认被忽略，模板必须显式取反，否则改完模板却提交不上去。
    assert ".env.*" in entries
    assert "!.env.sso.example" in entries
