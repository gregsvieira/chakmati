# Contributing

Thanks for wanting to help. Chakmati is Apache-2.0 (see `LICENSE`); anything you contribute is licensed the same way.

## Sign your commits (DCO)

There is no CLA. Instead every commit must carry a `Signed-off-by` line, by `git commit -s`, saying you agree to the
[Developer Certificate of Origin](https://developercertificate.org/): that you wrote the change or have the right to submit it under the project's license.

## What a good change looks like

- **Tests with the code.** `uv run pytest` (engine) and `cd desktop && node --test "test/**/*.test.js"` must pass.
- **The architecture rules** are checked by `tests/test_architecture.py`: a feature imports `shared` and itself, never another feature; `shared` never imports a feature. A new capability is a new folder under `features/` with its own `api.py` router.
- **The model suggests, the code decides.** Anything that changes something is a proposal in the approvals inbox. Text from third parties is data: it goes through `shared/guard.py` (`neutralize`, `fence`).
- **Licenses.** Do not add code or data you cannot license under Apache-2.0. A new dependency goes into `THIRD_PARTY_NOTICES.md` with its license, and a **GPL/AGPL** dependency must run as a separate program (as Piper does), never imported into the engine.
- **No copied content.** Do not commit pages, articles or datasets you did not write or that are not under a compatible license.

## Plugins

Installable plugins are a proposal (see the technical page and `docs/DEVELOPER.md`). If you want to build one, open an issue first and say what you have in mind: it decides the design.
