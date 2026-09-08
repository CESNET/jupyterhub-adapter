# Development, testing, and release preparation

## Local development environment

Create and activate an isolated virtual environment, then install the package and development tools:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Automated checks

Run the full local quality gate before every pull request:

```bash
black --check .
ruff check .
mypy fedcloud_jupyterhub
pytest -q
```

To let Black format the code automatically:

```bash
black .
```

Run tests with coverage when reviewing changes to behavior:

```bash
pytest --cov=fedcloud_jupyterhub --cov-report=term-missing
```

## Package build checks

Build both source and wheel distributions:

```bash
python -m build
```

Validate the generated package metadata:

```bash
python -m twine check dist/*
```

A useful final packaging smoke test is to create a new virtual environment and install the built wheel rather than the editable checkout:

```bash
python -m venv /tmp/jupyterhub-adapter-smoke
source /tmp/jupyterhub-adapter-smoke/bin/activate
python -m pip install dist/jupyterhub_adapter-1.0.0-py3-none-any.whl
python -c "from fedcloud_jupyterhub import JupyterHubClient; print(JupyterHubClient)"
fedcloud-jupyterhub --help
```

## PyPI release checklist

The repository is prepared for version `1.0.0`, but publication requires project-owner decisions and credentials that should not be committed to Git:

1. Confirm that the PyPI distribution name `jupyterhub-adapter` is the intended public name and is available or controlled by the project maintainers.
2. Confirm who owns/releases the project on PyPI and obtain permission for the release account or Trusted Publishing workflow.
3. Confirm the release version and Git tag naming convention (`1.0.0`, `v1.0.0`, or another project convention).
4. Run all automated checks and the live JupyterHub integration tests.
5. Build with `python -m build` and validate with `python -m twine check dist/*`.
6. Prefer PyPI Trusted Publishing from CI. If an API token is used instead, keep it only in the user's keyring/environment or CI secret storage.
7. Upload to TestPyPI first when possible, install the exact artifact in a clean environment, and repeat the smoke tests.
8. Publish the same verified artifacts to PyPI and create the matching GitHub release/tag.

Do not publish until the live Hub tests have confirmed that the 1.0 exception changes did not alter successful request semantics.
