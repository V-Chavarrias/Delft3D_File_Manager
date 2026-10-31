---
name: feature-delivery
description: "Use when adding or modifying Delft3D File Manager functionality, implementing or extending a feature, or refactoring feature logic. Plan, implement, document, test, and validate the change end-to-end."
argument-hint: "Describe the feature to add or modify"
---

Implement requested plugin functionality end-to-end. Plan first, then continue into implementation unless the user explicitly asks for a plan only.

## Workflow

1. **Scope and acceptance criteria**
   - Clarify the requested behavior, identify impacted modules, interfaces, and tests, and resolve material ambiguities before editing.
   - Record assumptions and open questions when details remain uncertain.
   - Define observable acceptance criteria and note relevant risks.
2. **Plan**
   - Provide an ordered, concrete plan with file-level changes for code, documentation, metadata, tests, and validation.
   - Keep the plan focused; do not stop at the plan unless the user requested plan-only work.
3. **Implement**
   - Make only the necessary changes, following existing patterns and avoiding unrelated refactors.
   - Never introduce broad exception handlers such as `except Exception: pass`; catch only documented, expected exception types and report handled failures explicitly through the repository's logging or user-notification mechanisms.
   - Update `README.md` for user-facing behavior changes.
   - Update the changelog in `Delft3DFileManager/metadata.txt`; recommend a version bump when appropriate.
   - Add or update meaningful tests for new behavior and regressions.
   - Keep reusable, checked-in test fixtures in `data/`. Create generated test inputs and outputs under pytest `tmp_path`. Never put test data in, read from, or otherwise depend on `data_tmp/`; tests must work from a fresh checkout.
   - When adding postprocessing for a variable, support both 1D and 2D data, both on-the-fly computation for large files without loading the entire file and computation from an already-loaded mesh layer. Test each supported dimension and data-source combination.
4. **Validate**
   - Run focused tests for the change, then the full testbench with `python -m pytest tests/ -v`.
   - Run any additional repository CI gates that apply, including coverage thresholds, and fix failures before concluding.
   - Report skipped or environment-dependent checks explicitly; do not claim a test passed unless it was run.
5. **Report**
   - Summarize the plan and acceptance criteria.
   - List code and documentation changes by file.
   - Report testbench commands and results, including relevant skips or limitations.
   - End with concise, release-note-ready bullets.

Return format:
1. Plan
2. Code/doc changes
3. Testbench result
4. Release-note-ready bullets
