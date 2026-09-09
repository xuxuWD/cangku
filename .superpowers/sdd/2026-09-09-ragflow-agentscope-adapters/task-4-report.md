# Task 4 Report

## Scope

Integrated RAGFlow and AgentScope into the controlled Runtime registry and added fixed-version configuration validation.

## Changes

- Added `version: str` to `RuntimeEndpointConfig`.
- Registered `ragflow` with `RAGFlowAdapter`.
- Registered `agentscope` with `AgentScopeAdapter`.
- Added fixed-version validation for enabled external Runtimes.
- Rejected missing, blank, `latest`, `main`, and `head` versions.
- Added positive finite timeout validation for enabled external Runtimes.
- Kept the default registry limited to `mock`.
- Updated existing enabled Runtime test fixtures to include a pinned version.
- No credentials, authentication headers, cookies, or API keys were added to configuration or payloads.

## TDD Evidence

1. Added registry tests for explicit RAGFlow/AgentScope registration, fixed versions, and default behavior.
2. Ran the focused test file before implementation; 7 tests failed because the constructors and version validation were absent.
3. Implemented the minimal registry changes.
4. Ran focused and related Runtime tests successfully.

## Verification

Command:

```text
python -m pytest -q tests/test_runtime_registry_config.py tests/test_runtime_adapters.py tests/test_runtime_http_transport.py tests/test_runtime_contracts.py tests/test_ragflow_adapter.py
```

Result:

```text
39 passed
```

## Commit

`feat: 注册 RAGFlow 与 AgentScope 并校验版本`
