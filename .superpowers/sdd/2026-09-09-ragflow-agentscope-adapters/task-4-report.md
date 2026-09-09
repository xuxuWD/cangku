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

## Review Fixes

- Added a management health response for the knowledge-only RAGFlow adapter with explicit `unavailable` status.
- Added `RuntimeUnavailable` for RAGFlow execution operations so `RuntimeService.start` returns a controlled lookup-style failure instead of `AttributeError`.
- Added a no-op checkpoint lookup so `RuntimeService.adapter_for` can safely skip RAGFlow when resolving executable runs.
- Normalized Runtime versions with `strip()` before reserved-value checks and storage.
- Rejected malformed capability values unless they are a non-empty list/tuple of non-empty strings.

## Review Verification

```text
python -m pytest -q
191 passed
```
