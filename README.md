# JupyterHub Adapter

`jupyterhub-adapter` is a standalone Python library for common JupyterHub operations used by EOSC/EGI integrations. It can be imported directly from Python applications, services, notebooks, or automation code. An optional Click CLI is included, but the CLI is only a thin presentation layer over the library API.

The adapter covers:

- user and server discovery;
- server start and stop operations;
- server sharing management;
- JupyterHub API token management;
- file and directory operations through the Jupyter Contents API;
- local file upload;
- command execution through the JupyterLab control endpoint.

## Installation

Install the package from a local checkout during development:

```bash
python -m pip install -e .
```

Install development tools as well:

```bash
python -m pip install -e ".[dev]"
```

After the first PyPI release, the normal installation command will be:

```bash
python -m pip install jupyterhub-adapter
```

## Basic library usage

`JupyterHubClient` is the recommended public interface. Connection-wide values such as `hub_api_endpoint`, `token`, and an optional default `user` are configured once and reused by all operations:

```python
from fedcloud_jupyterhub import JupyterHubClient

client = JupyterHubClient(
    hub_api_endpoint="https://hub.example/hub/api/",
    token="<hub-api-token>",
)

user = client.get_user(include_stopped_servers=True)
servers = client.get_servers()
client.start_server(server="")
```

A default target user can also be stored on the client:

```python
client = JupyterHubClient(
    hub_api_endpoint="https://hub.example/hub/api/",
    token="<hub-api-token>",
    user="alice",
)

servers = client.get_servers()
```

Individual calls may override that default user when necessary:

```python
other_servers = client.get_servers(user="bob")
```

For backwards compatibility and one-off calls, the module-level functional API remains available. New integrations should prefer `JupyterHubClient` because it avoids repeating the Hub endpoint and token for every operation.

```python
from fedcloud_jupyterhub import get_user

user = get_user(
    hub_api_endpoint="https://hub.example/hub/api/",
    token="<hub-api-token>",
)
```

## Error handling

Library methods raise typed exceptions instead of printing operational errors or silently returning `None` for failures. Applications can therefore decide how to recover, report, or log errors:

```python
from fedcloud_jupyterhub import (
    JupyterHubAPIError,
    JupyterHubClient,
    JupyterHubNotFoundError,
    JupyterHubRequestError,
)

client = JupyterHubClient(
    hub_api_endpoint="https://hub.example/hub/api/",
    token="<hub-api-token>",
)

try:
    servers = client.get_servers()
except JupyterHubNotFoundError as exc:
    print(f"The requested Hub resource does not exist: {exc}")
except JupyterHubAPIError as exc:
    print(f"JupyterHub returned HTTP {exc.status_code}: {exc.message}")
except JupyterHubRequestError as exc:
    print(f"The Hub could not be reached: {exc}")
```

Applications may configure standard Python logging for `fedcloud_jupyterhub` if they want diagnostic messages from the adapter. The library does not configure global logging handlers itself.


## Command execution support

`JupyterHubClient.exec_command()` and the CLI `execute` subcommand require the
`jupyterlab_control_exec` Jupyter Server extension to be installed and enabled
in the target single-user environment. The extension provides the
`POST /jlab-control/exec` endpoint used by the adapter.

The extension is a **server-side prerequisite**, not a normal client-side
dependency of `jupyterhub-adapter`. Installing the adapter on a workstation does
not install software into remote single-user notebook environments. The
extension therefore needs to be included in the single-user image or otherwise
installed in the Python environment that runs Jupyter Server.

Until the extension is published as an installable release, it can be installed
from its repository, for example:

```bash
python -m pip install git+https://gitlab.cesnet.cz/jaromir.hradil/jupyterlab-control-extension.git
```

Verify the server-side installation with:

```bash
jupyter server extension list
```

If the extension is missing or disabled, command execution will fail because
`/jlab-control/exec` is unavailable. The adapter reports an HTTP 404 with an
explicit message pointing to the missing server extension.

## Optional CLI

The standalone command is installed as:

```bash
fedcloud-jupyterhub --help
```

The CLI creates a `JupyterHubClient` internally and invokes the same public methods documented for Python callers. The Click group can also be embedded into another Click application, including `fedcloudclient`:

```python
from fedcloud_jupyterhub.cli import jupyterhub

cli.add_command(jupyterhub)
```

## Documentation

- [Public Python API](docs/api.md)
- [Exception model and logging](docs/errors.md)
- [Development, tests, and release preparation](docs/development.md)

## License

Apache License 2.0.
