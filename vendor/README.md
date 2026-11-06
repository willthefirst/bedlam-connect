# Vendored libraries

Third-party (or sibling-project) source that ships inside this repo because it is built or copied from here rather than installed from a registry. Each subdirectory is the upstream tree, with its own README, plus any local patches the consuming code's README lists; the *integration* — which files were copied into `src/`, what was changed, how to upgrade — is documented next to the consuming code, not here.

- `storyteller/` — the Storyteller visit-story service. Its Docker image is built from this tree by CD; the consumer adapter and browser snippet copied into the app are documented in [`src/domain/logic/storyteller/README.md`](../src/domain/logic/storyteller/README.md).

Excluded from `black`/`isort`/title-case checks (see `pyproject.toml`) and from pytest collection (`testpaths`): upstream's style is upstream's business.
