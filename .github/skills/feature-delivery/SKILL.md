---
name: feature-delivery
description: Implement new plugin functionality with mandatory README, metadata/changelog, tests, and passing testbench
disable-model-invocation: true
argument-hint: "Describe the feature to add or modify"
---
Implement the requested plugin functionality end-to-end.

Requirements:
- Create a concrete implementation plan first.
- Implement only the necessary code changes.
- Update README.md for any user-facing behavior change.
- Update Delft3DFileManager/metadata.txt changelog and bump version when appropriate.
- Add or update tests in tests/ that cover new behavior and regressions.
- When adding postprocessing for a variable, support both 1D and 2D data, and computation both on the fly for large files without loading the entire file and from an already-loaded mesh layer. Test the supported dimension and data-source combinations.
- Keep reusable test fixtures in `data/` and generated test files in `tmp_path`; never put test data in or depend on `data_tmp/`.
- Run full testbench with pytest tests/ -v and fix failures.

Return format:
1. Plan
2. Code/doc changes
3. Testbench result
4. Release-note-ready bullets
