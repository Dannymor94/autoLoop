# Disposable E2E source fixture

Copy this directory into a NEW isolated GitHub test repository and commit the
baseline BEFORE starting a real paid/subscription agent. Baseline tests must
fail with `NotImplementedError` by design. The frozen task is specified in
`../ACCEPTANCE.md` and must not be rewritten after the baseline is recorded.

Do not point the real runner at the autoLoop project or any production repo.
