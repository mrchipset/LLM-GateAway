# LLM-GateAway Collaboration Rules

This file is for everyone and every coding agent working in this repository. It contains durable collaboration rules, engineering boundaries, and quality standards only.

## 0. What this file must not contain

Do not write content that changes with the code. This includes:

- directory trees, file inventories, module inventories
- dependency names, dependency versions, tool versions
- endpoint lists, model lists, provider lists
- current feature status, backlog, roadmap, sprint plans
- exact startup, test, or deployment commands
- machine paths, ports, accounts, secrets, internal URLs
- current line counts or the current methods of a class

These belong to a single source of truth:

| Content | Source of truth |
|---|---|
| How to install, run, deploy | `README.md` |
| Current architecture snapshot and request flow | `architecture.md` |
| Design decisions, trade-offs, technology choices | `design.md`, ADRs |
| Working design reasoning, options, trade-offs | `notes/` |
| Dependencies, scripts, formatting | build manifests, task runner, CI config |
| Checks that CI actually runs | CI config |
| Current features and progress | issue tracker, milestones |
| Rules for one directory | that directory's `AGENTS.md` |

Test: if a rule only makes sense with the current directory tree in front of you, it does not belong here.

The root `AGENTS.md` governs the whole repository. A nested `AGENTS.md` governs its directory. The more specific rule wins. Delete or rewrite stale, duplicated, or unenforceable rules. Do not turn this file into a changelog.

## 1. Language and output

- All agent reasoning, analysis, planning, and internal deliberation must be in English. Do not produce Chinese reasoning.
- All user-facing output, including chat replies, explanations, summaries, and questions, must be in Chinese by default.
- Documents intended for the user, such as `architecture.md`, `design.md`, `README.md`, ADRs, runbooks, and review notes, must be written in Chinese by default.
- Code, identifiers, code comments, commit messages, branch names, API field names, log messages, and configuration keys must be in English.
- Working design notes under `notes/` are written in English. If a note becomes a user-facing document, move the durable decision into the appropriate Chinese document or ADR.
- If the user explicitly asks for another language, follow that request for the relevant output only.
- Keep this file in English to reduce token overhead. Do not translate it into Chinese.
- Chinese documents may keep English technical terms when that is clearer than a translation.

## 2. Think before coding

- State assumptions before acting. Ask when unsure. Do not guess critical paths, interface contracts, or data semantics.
- When multiple interpretations are reasonable, list them. Do not silently pick one.
- If a simpler approach exists, say so before deciding to proceed with the original plan.
- If requirements are unclear, stop, name the confusion, and ask.
- Define boundaries, contracts, and data flow before writing implementation.
- Solve the problem with the smallest change. Do not add unrequested features, abstractions, configuration, or error handling.
- If 200 lines can be 50, rewrite.

## 3. Code quality

Priority order: correct, secure, performant, readable, maintainable, modern.

- Composition over inheritance.
- Early returns over deep nesting.
- Dependency injection. Do not construct external dependencies inside core logic.
- Public boundaries must be typed. Do not let `Any`, bare `dict`, or untyped objects escape.
- Fail explicitly. Do not swallow exceptions, add silent fallbacks, or downgrade errors to empty results.
- Prefer immutability. Avoid global mutable state. Shared state must document its lifetime and concurrency model.
- Prefer the standard library, official SDKs, and mature libraries. Do not hand-roll existing standards.
- No giant files or god objects. Split by domain, not by technical layer.
- No copy-paste. Extract shared logic, but do not build abstractions for single-use code.
- Comments only for non-obvious business logic or tool directives. Do not restate code.
- `TODO` and `FIXME` must explain why they exist or link to a tracking issue.
- Public API, configuration format, and database schema changes must consider backward compatibility. Breaking changes need versioning or a migration period.
- Do not bypass lint, format, or typecheck. A suppression must name the exact rule and the reason.

## 4. Testing

Every new feature must have unit tests. Every bug fix must have a regression test that reproduces the bug. A feature without tests is not done.

Testing principles:

- Test behavior, not implementation. Do not assert private methods, file structure, module paths, or internal call order.
- A test must fail when behavior breaks. Write the failing test first, then implement until it passes.
- Do not write empty tests for coverage. One test that kills a mutation is better than ten tests that only execute code.
- Unit tests must be fast, deterministic, and isolated. No network, no subprocess, no real time, no randomness, no machine state.
- Use fixed or injected clocks for time-dependent logic. Use fixed seeds for randomness.
- Do not pin third-party facts such as vendor prices, upstream defaults, or today's date. Assert invariants your own code guarantees.
- One behavior per test. The name should describe what broke. Avoid `test_works` or `test_success`.
- Failure messages must locate the problem. Put context in the assertion message, not in a comment.
- Do not mock your own core logic. Replace external dependencies with injected fakes.
- Layer unit, integration, and end-to-end tests. Tests that need a real database, a real provider, or a real key must be explicitly marked and skipped by default.
- Run affected tests before committing. Expand to related integration tests only for cross-module changes. Do not run everything out of habit.

Test location, framework, and commands are defined by the project's test configuration and CI. Do not copy these volatile details into this file.

## 5. Git workflow

The repository root must be a git repository. When bootstrapping the project, initialize git and add an appropriate `.gitignore`.

A staged feature is a behavior change that can be reviewed independently. It must satisfy:

- complete behavior, not a half-finished slice
- unit tests cover the new behavior; bug fixes have regression tests
- affected tests pass
- lint, format, and typecheck pass
- no debug code, temporary logs, or commented-out tests
- no secrets, `.env` files, build artifacts, caches, local databases, or logs
- the diff has been self-reviewed

Commit immediately after completing such a stage. Do not leave completed stages in the working tree indefinitely. Do not mix unrelated changes in one commit.

Commit rules:

- Use Conventional Commits: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`, `perf:`, `build:`, `ci:`.
- Explain why the change is needed, not just which files changed.
- One topic per commit. Keep formatting, renames, and behavior changes separate.
- Sync with the remote before starting work. Do not develop on a stale branch.
- Do not force-push shared branches or rewrite other people's history.
- Do not add AI attribution, `Co-Authored-By`, or `Generated with` lines.
- Do not put customer names, internal project names, or sensitive information in commit messages.

## 6. Security

- Read secrets only from environment variables or a secret manager. Never put them in code, sample configs, tests, logs, or commits.
- Authentication is on by default. Management APIs must be authenticated. Do not assume the network is safe.
- Least privilege. Do not grant a service account, key, or process more permissions than it needs.
- Validate all external input at the boundary. Do not trust client-supplied user, team, model, or permission fields.
- Error messages must not leak internal paths, SQL, stack traces, or credentials.
- Redact logs. Do not log full prompts, completions, tokens, or personal data unless explicitly required and compliant.
- Pin dependencies. Verify checksums for CI downloads. Never pipe a remote script into a shell.
- Do not put customer company names in code, issues, pull requests, or docs. Say "the customer" when needed.
- Handle security reports privately. Do not post exploit details in public issues.

## 7. API and protocol

- Keep the inference API OpenAI-compatible to reduce client integration cost.
- Keep the management API separate from the inference API, with different path prefixes and authentication.
- Return a consistent error structure with stable error codes and a request id.
- For streaming, define first-chunk errors, client disconnect, cancellation, and resource release semantics.
- List endpoints support pagination, filtering, and sorting. Write endpoints consider idempotency keys.
- Version public contract changes, or provide a compatibility window. Do not silently change field semantics.
- Keep provider differences inside the adapter boundary. Do not leak them into routing or the main flow.

## 8. Observability

Every request must answer:

- who called, and which key, team, model, and deployment were used
- input and output tokens, cost, time to first token, and total latency
- status code, error type, cache hit, retry, and fallback
- request id and trace id

Requirements:

- Structured logs with stable fields and appropriate levels.
- Metric labels must stay low-cardinality. Do not use user input, prompts, or request ids as labels.
- Redact sensitive fields.
- Failure paths must be observable too. Do not log only successful requests.

## 9. Performance and reliability

- Measure before optimizing. Do not rewrite large areas without a profile or benchmark.
- Use async I/O. Do not run blocking calls in the event loop.
- Every network call must have a timeout. Retries must be bounded, with backoff and jitter.
- Define behavior for rate limiting, circuit breaking, backpressure, and full queues.
- Do not introduce Rust, Go, complex caches, or microservices for imagined performance.
- Fallbacks and degradation must log and emit metrics. They must never be silent.
- Resource release must cover success, error, cancellation, and timeout.

## 10. Documentation and decisions

- `architecture.md` and `design.md` are current snapshots, not permanent rules. Update them when architecture or choices change.
- Write an ADR for irreversible or expensive decisions. Record context, options, decision, and consequences.
- `README.md` explains usage. `AGENTS.md` explains collaboration. Do not mix the two.
- Docs must not duplicate code, configuration, or commands. Link to the single source of truth.
- Put directory-specific rules in that directory's `AGENTS.md`, not in the root file.
- When docs and code disagree, confirm the real behavior first, then fix the docs or the code. Do not leave ambiguous guidance in both places.

## 11. Design notes

During implementation, record important design reasoning in `notes/`. This is required for non-trivial changes, not optional.

A design note should capture:

- the problem and constraints
- assumptions and open questions
- options considered and why they were rejected
- the chosen approach and the reasoning behind it
- trade-offs, risks, and anything a future maintainer would need
- links to relevant code, issues, ADRs, or external references

Rules:

- Write the note while you are implementing, not as an after-the-fact summary.
- One note per staged feature or significant decision. Use a descriptive file name.
- Keep notes short and focused. Prefer bullets, small diagrams, and links over pasted code or full logs.
- Write notes in English. They are part of engineering reasoning and use the same token-efficient language.
- Do not put secrets, customer names, personal data, or credentials in notes.
- Notes are working documents, not a replacement for ADRs or user-facing docs. When a decision becomes durable, promote it to an ADR or the appropriate document, then keep the note as context or delete it.
- Commit the note with the feature. If a note is purely transient scratch work, do not commit it.
- Do not create a single giant notes file. Do not use notes as a task tracker.

## 12. Definition of done

A task is done only when:

- behavior matches the requirement, including edge cases
- new behavior has unit tests, and bugs have regression tests
- affected tests pass
- lint, format, and typecheck pass
- public contracts, configuration, or docs are updated where needed
- important design reasoning is captured in `notes/` for non-trivial changes
- no secrets, debug code, build artifacts, or temporary files remain
- the diff is self-reviewed and the commit message is clear
- the work is committed to git according to section 5

## 13. Prohibited

- writing directory structure, file inventories, dependency versions, endpoint lists, or feature status into this file
- committing code that cannot run, or skipping or commenting out failing tests
- tests that only assert implementation details or exist for coverage
- swallowed exceptions, silent fallbacks, or network calls without timeouts
- giant files, copy-paste, or abstractions for single-use code
- committing secrets, customer names, AI attribution, or unrelated formatting changes
- introducing new technology, rewriting core paths, or splitting services without measurement
- skipping design notes for non-trivial changes
- putting secrets, customer names, or personal data in `notes/`

## 14. Maintaining this file

- When a rule causes real friction, discuss it before changing it. Do not loosen a rule just to let one violation pass.
- Delete or rewrite rules that are stale, duplicated, or unenforceable. Do not preserve historical baggage.
- Review this file after architecture, process, or tooling changes.
- Move enforceable rules into lint, typecheck, CI, and tests whenever possible.
- Keep this file short. It should help people do the right thing quickly, not become a manual.
