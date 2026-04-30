---
name: Bug report
about: Report something that doesn't work
title: "[bug] "
labels: bug
assignees: ''
---

## What happened?

<!-- A clear, concise description of the problem -->

## What did you expect?

<!-- What should have happened instead -->

## Repro

```bash
# exact command line you ran (redact API keys)
python <module>.py --url ...
```

## Output / traceback

```
<paste full stderr here, redacting any tokens>
```

## Environment

- OS: <!-- Windows 11 / macOS 14 / Ubuntu 24.04 / etc. -->
- Shell: <!-- PowerShell 7 / bash / zsh / cmd -->
- Python: <!-- output of `python --version` -->
- Project commit: <!-- output of `git rev-parse --short HEAD` -->
- Target URL public? Yes / No

## Have you tried?

- [ ] Latest commit on `main`
- [ ] `python -m py_compile <module>.py` (does it at least parse?)
- [ ] Searched existing issues
