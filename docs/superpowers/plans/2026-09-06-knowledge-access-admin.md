# 知识权限管理台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first production-ready React admin page for Chinese knowledge-access configuration, connected to the existing `/api/v1` contract and matching the approved v8 light skeuomorphic visual system.

**Architecture:** Create an `admin-web/` Vite React TypeScript application inside the isolated worktree. Keep API access in a typed service module, state and interaction orchestration in the page layer, and visual primitives in focused components with semantic CSS tokens. The page defaults to role scope management, supports agent scope management, and gracefully handles loading, unauthorized, network, save, and audit states.

**Tech Stack:** React 18, TypeScript, Vite, Vitest, Testing Library, CSS modules/global tokens, Fetch API.

---

### Task 1: Create the frontend project foundation

**Files:**
- Create: `admin-web/package.json`
- Create: `admin-web/tsconfig.json`
- Create: `admin-web/tsconfig.node.json`
- Create: `admin-web/vite.config.ts`
- Create: `admin-web/index.html`
- Create: `admin-web/src/main.tsx`
- Create: `admin-web/src/app/App.tsx`
- Create: `admin-web/src/app/App.test.tsx`

- [ ] **Step 1: Write the failing smoke test**

Create a test that renders the app and expects the Chinese page title and the role/agent switch labels.

- [ ] **Step 2: Run the test to verify it fails**

Run `npm test -- --run` from `admin-web/`. Expected: fail because the project files do not exist.

- [ ] **Step 3: Add the Vite/React TypeScript foundation**

Use an npm script set of `dev`, `build`, `test`, and `test:watch`; configure Vitest with a jsdom environment and Testing Library setup.

- [ ] **Step 4: Implement the minimal App shell**

Render a semantic `<main>` with `知识权限管理`, `岗位权限`, and `数字员工权限` so the smoke test passes.

- [ ] **Step 5: Run the test and production build**

Run `npm test -- --run` and `npm run build`; expected: both pass.

- [ ] **Step 6: Commit**

Commit as `feat: scaffold admin web app`.

### Task 2: Add design tokens and reusable visual primitives

**Files:**
- Create: `admin-web/src/styles/tokens.css`
- Create: `admin-web/src/styles/global.css`
- Create: `admin-web/src/components/FilledIcon.tsx`
- Create: `admin-web/src/components/SegmentedControl.tsx`
- Create: `admin-web/src/components/ObjectSelect.tsx`
- Create: `admin-web/src/components/NoticeBanner.tsx`
- Create: `admin-web/src/components/Toast.tsx`
- Create: `admin-web/src/components/SaveButton.tsx`
- Create: `admin-web/src/components/visual-primitives.test.tsx`
- Modify: `admin-web/src/main.tsx`

- [ ] **Step 1: Write failing component tests**

Cover selected segment semantics, icon `aria-label`, save button loading/disabled text, and notice error/sensitive variants.

- [ ] **Step 2: Run focused tests and verify failure**

Run `npm test -- --run src/components/visual-primitives.test.tsx`; expected: fail because components and tokens are missing.

- [ ] **Step 3: Define semantic tokens**

Create light skeuomorphic tokens for canvas, surface, text, separator, cyan/blue technology emphasis, green success, orange warning, shadows, spacing, radii, and motion. Add `prefers-reduced-motion` handling globally.

- [ ] **Step 4: Implement primitives**

Use CSS-drawn filled geometric icons only; no emoji and no external line-icon package. Components must expose native button semantics, visible focus, minimum 44px touch targets, and Chinese labels.

- [ ] **Step 5: Run tests and build**

Expected: focused tests and `npm run build` pass.

- [ ] **Step 6: Commit**

Commit as `feat: add admin design system primitives`.

### Task 3: Implement typed knowledge-access API and state model

**Files:**
- Create: `admin-web/src/features/knowledgeAccess/api.ts`
- Create: `admin-web/src/features/knowledgeAccess/types.ts`
- Create: `admin-web/src/features/knowledgeAccess/state.ts`
- Create: `admin-web/src/features/knowledgeAccess/api.test.ts`

- [ ] **Step 1: Write failing API tests**

Mock `fetch` and assert role GET/PUT, agent GET/PUT, audit GET, 403 normalization, non-OK error normalization, and deterministic idempotency key headers for saves.

- [ ] **Step 2: Run focused tests and verify failure**

Run `npm test -- --run src/features/knowledgeAccess/api.test.ts`; expected: fail because the typed client is missing.

- [ ] **Step 3: Define API types and client**

Model `knowledge_base_ids`, binding type/key, audit records, and a Chinese `ApiError`. Use `VITE_API_BASE_URL` with `/api/v1` default, `X-Tenant-Id`, `X-User-Id`, and `X-User-Role` only for development configuration. Never log response bodies containing secrets.

- [ ] **Step 4: Add reducer/state helpers**

Represent selected subject, scope IDs, initial scope IDs, loading state, saving state, save error, authorization error, audit loading, and toast state. Preserve local selections when saving fails.

- [ ] **Step 5: Run tests and build**

Expected: focused API tests and production build pass.

- [ ] **Step 6: Commit**

Commit as `feat: add knowledge access api client`.

### Task 4: Build the knowledge permission page

**Files:**
- Create: `admin-web/src/features/knowledgeAccess/KnowledgeAccessPage.tsx`
- Create: `admin-web/src/features/knowledgeAccess/KnowledgeScopeRow.tsx`
- Create: `admin-web/src/features/knowledgeAccess/AuditTimeline.tsx`
- Create: `admin-web/src/features/knowledgeAccess/SoundPreference.tsx`
- Create: `admin-web/src/app/AppShell.tsx`
- Modify: `admin-web/src/app/App.tsx`
- Modify: `admin-web/src/styles/global.css`
- Create: `admin-web/src/features/knowledgeAccess/KnowledgeAccessPage.test.tsx`

- [ ] **Step 1: Write failing page tests**

Cover loading skeleton, role scope success, agent tab switch, toggle count, clear action, save loading/success, 403 unauthorized state, network error with retry, and audit rendering.

- [ ] **Step 2: Run focused tests and verify failure**

Run `npm test -- --run src/features/knowledgeAccess/KnowledgeAccessPage.test.tsx`; expected: fail because the page is not implemented.

- [ ] **Step 3: Implement the page and shell**

Build the approved v8 structure: top bar, management navigation, central content-driven list rows, warning notice, latest change, right-side audit timeline, sound preference, and responsive collapse. Use real API calls via the client and keep all labels ordinary Chinese.

- [ ] **Step 4: Implement interaction behavior**

Toggles update local state and selected count; clear requires confirmation when selections exist; save disables duplicate clicks, sends an idempotency key, shows loading then success Toast, and keeps selections on failure. Unauthorized users see a clear explanation and no executable save controls.

- [ ] **Step 5: Add accessible feedback**

Use `aria-live` for Toast and request status, `aria-pressed`/`aria-selected` for controls, visible focus rings, keyboard-safe buttons, and a `prefers-reduced-motion` fallback. Sound is opt-out and only triggered by explicit interaction.

- [ ] **Step 6: Run page tests and build**

Expected: page tests and `npm run build` pass.

- [ ] **Step 7: Commit**

Commit as `feat: build knowledge access admin page`.

### Task 5: Verify desktop/mobile visuals and delivery gates

**Files:**
- Create: `admin-web/README.md`
- Modify: `README.md`
- Modify: `.gitignore` if needed

- [ ] **Step 1: Start the frontend dev server**

Run `npm run dev -- --host 127.0.0.1` from `admin-web/` and record the local URL.

- [ ] **Step 2: Verify browser states**

Use Playwright/browser inspection at 1440px, 1024px, 768px, and 390px. Confirm no horizontal overflow, no text touching card edges, stable row heights, responsive sidebar collapse, and complete save/error feedback.

- [ ] **Step 3: Run all frontend checks**

Run `npm test -- --run`, `npm run build`, and `git diff --check`. Expected: all pass.

- [ ] **Step 4: Document setup and API configuration**

Document `npm install`, `npm run dev`, `VITE_API_BASE_URL`, and development identity headers. Explicitly state that production authentication replaces development headers.

- [ ] **Step 5: Commit**

Commit as `docs: document admin web setup`.

## Self-review

- Covers approved visual direction, Chinese naming, filled icon rule, content-driven spacing, complete states, sound, reduced motion, API contract, responsive behavior, and browser validation.
- No arbitrary third-party assets or private-interface automation is included.
- The plan keeps the first frontend slice bounded to knowledge-access administration; it does not expand into the entire employee workbench.
