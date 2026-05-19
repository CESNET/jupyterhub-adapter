# fedcloud-jupyterhub-client

Standalone Python client and Click CLI for interacting with JupyterHub APIs.

The package exposes library functions from `fedcloud_jupyterhub.client` and a reusable Click command group in `fedcloud_jupyterhub.cli:jupyterhub`.

## Install locally

```bash
pip install -e .
```

## CLI

```bash
fedcloud-jupyterhub --help
```

The command group can also be embedded into another Click application:

```python
from fedcloud_jupyterhub.cli import jupyterhub

cli.add_command(jupyterhub)
```
