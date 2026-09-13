# AGENTS.md — paragliding_site_federation

Branching, commits, PRs and merges follow the global `~/.dsh/AGENTS.md` rules
(branch or worktree first, squash-merged PRs, `main` stays clean, trivial fixes may
land directly on `main`). Only repo-specific facts live here.

## What this repo is

Cross-references national paragliding site guides against ParaglidingEarth (PGE)
and proposes reviewed site links as pull requests. Nothing is written back to PGE
or any upstream guide. Background and the worked examples (AU, DHV) are in
`README.md`.

## Hard rules

- **Python 3.11+.** Dependencies are deliberately small (`httpx`, `rapidfuzz` — see
  `pyproject.toml`); keep new ones justified.
- **A federated site keeps its `pge:` key.** Devices already store it; a link or
  merge decision must never drop it (see the README's merge counts).
- **Read-only toward upstreams.** All output lands in `reports/` and `state/`;
  nothing is pushed back to PGE or any national guide.
- New source adapters live in `src/sources/` and need their identity fields
  (`label`, `full_name`, `homepage`, `site_url_template` — see `src/sources/base.py`)
  plus a listing in the source registry.

## Commands

```
pytest -q    # suite; run from the repo root (pythonpath=["."] is set in pyproject.toml)
```

This machine has no system pip — use a project venv (uv) as in the sibling
`forecast-accuracy` repo, and see the global `machine-env` skill for the sandbox
facts before debugging "missing" tools.
