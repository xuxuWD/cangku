from app.runtime.staging import run_smoke_check


def test_staging_smoke_check_covers_all_runtime_boundaries() -> None:
    report = run_smoke_check()

    assert report["status"] == "pass"
    assert report["runtimes"] == {
        "mock": "pass",
        "deerflow": "pass",
        "codex_worker": "pass",
        "hermes": "pass",
    }
    assert report["security"] == {
        "context_scope": "pass",
        "secret_redaction": "pass",
        "hermes_review_gate": "pass",
    }
