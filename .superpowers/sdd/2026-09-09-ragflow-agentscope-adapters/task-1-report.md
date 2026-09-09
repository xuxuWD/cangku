# Task 1 Report: Knowledge Retrieval Contract and Transport Boundary

## Result

Implemented the runtime knowledge citation contract and read-only knowledge search transport boundary.

## TDD Evidence

### RED

Added the required focused tests:

- `test_knowledge_citation_requires_the_public_reference_fields`
- `test_http_transport_searches_knowledge_without_exposing_internal_fields`

The first focused run failed during test collection because `KnowledgeCitation` was not yet defined in `app.runtime.contracts`. This was the expected missing-feature failure.

### GREEN

After the minimal implementation, the focused tests passed:

```text
.. [100%]
```

The related runtime tests also passed:

```text
............ [100%]
```

The full suite passed:

```text
144 passed
```

`git diff --check` passed.

## Files Changed

- `app/runtime/contracts.py`
  - Added immutable `KnowledgeCitation` with public reference fields and optional score.
- `app/runtime/adapters/common.py`
  - Added `HttpRuntimeTransport.knowledge_search()`, using only the fixed `/knowledge-search` path through `_request`.
  - Added injectable `knowledge_items` and request recording support to `FakeTransport`.
- `app/runtime/adapters/__init__.py`
  - Exported the existing `ExternalAdapter` transport/adapter base while preserving existing adapter exports.
- `tests/test_runtime_contracts.py`
  - Added the citation contract test.
- `tests/test_runtime_http_transport.py`
  - Added the HTTP knowledge search boundary test.

## Self-Review

- The new citation is `frozen=True`, matching the existing runtime value-object style.
- HTTP search reuses the existing error handling, response-shape validation, and endpoint normalization.
- Fake transport returns a copied item list and records the request without introducing external side effects.
- Existing lifecycle transport behavior and adapter exports remain compatible.

## Concerns

- Authentication headers and deployment-level secret injection remain outside this task, as required by the implementation plan.
- The transport method intentionally returns raw dictionaries; citation field validation and tenant/scope enforcement belong to the RAGFlow adapter task.
