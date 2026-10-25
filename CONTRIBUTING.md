# Contributing

Thanks for taking an interest in `ha-solcast-solar`. This is a small project, maintained by only a couple of contributors, so although there's no formal process to wade through — just clone it, make your change, and open a PR, there are some rules and some expectations. This document sets out those rules and expectations:  An associated document - [DEVELOPERS.md](DEVELOPERS.md) sets out how to get a dev environment running, how to get tests running, the expectations about testing, and coding conventions and quality.

There's no way to run this integration standalone outside Home Assistant — `coordinator.py`, `config_flow.py`, etc. all import `homeassistant.*`, so it only loads inside a real HA instance or Dev Container.

## AI

### Acceptable

AI Assistance in development, and especially in development of testing is acceptable, but must be declared in any PR.

### Unacceptable

AI Generated PRs or Issues are likely to be closed as not planned unless they happen to uncover a catastrophic latent defect and provide a perfectly documented and tested fix, and a justification for the fix at the same time.

In other words, solutions looking for a problem are not welcome.

## Linting

```bash
ruff check .
ruff format .
```

Please run both before opening a PR.

Configuration lives in `pyproject.toml` — if you are using the supplied pyproject.toml from the Home Assistant Dev Container, as we support older versions of home assistant than the latest dev version, you will want to make some changes to the supplied template:

```toml
[tool.ruff]
required-version = ">=0.16.8"
line-length = 150
target-version = "py313"
```

Remove the line:
`"__future__.annotations".msg = "It should not be needed because Home Assistant requires Python 3.14+"`

## Key Expectations

Present PyTest coverage of all modules is 100%. Every statement of code is currently exercised, and it is expected that every circumstance is covered by a test. (This may be accomplished by extending an existing test, or by creating a new one.) This is something that should be aspired to for every pull request to this integration, and if test coverage is completely ignored and your pull request is extensive, then it will likely be rejected, even if it appears to work perfectly. (If your test does not hit PyTest 100% coverage then someone else will need to code the test properly before the code is released.)

Home Assistant development standards to Platinum level is also a thing here, and non-conformance will also result in PR revisions required, or rejection. A strict type checking standard is maintained. The Home Assistant dev container incorporates much automated checking of code standards to help out, but you will likely need to add PyLance and configure type checking to strict standard. GitHub Copilot is also pretty neat at calling out inefficient or poorly constructed code, and this can also be used in the dev container.

## Pull requests

A few practical guidelines, gathered from how this repo has actually been worked so far:

- Branch off an up-to-date `main`, e.g. `feat/short-description` or `fix/short-description`.
- Keep PRs to one logical change — easier to review, and it keeps the generated changelog readable.
- Run `python3 -m pytest` and `ruff check . && ruff format --check .` locally before pushing.
- Open the PR against `main` via `gh pr create` (or the GitHub UI).
- For the PR description, a short **Summary** section (a few bullet points on what changed and why) plus a **Test plan** checklist (what you ran, what still needs manual verification if anything) is the format this repo has settled into — see recent merged PRs for examples of the level of detail that's useful.
