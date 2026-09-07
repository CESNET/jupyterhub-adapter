# Public Python API

The recommended public API is the `JupyterHubClient` class imported from `fedcloud_jupyterhub`. The client stores the JupyterHub REST API endpoint and authentication token once, so individual operations only require parameters specific to that operation.

Unless stated otherwise, `hub_api_endpoint` is the JupyterHub REST API base URL, normally ending in `/hub/api/`, and `token` is a JupyterHub API token.

## Creating a client

```python
from fedcloud_jupyterhub import JupyterHubClient

client = JupyterHubClient(
    hub_api_endpoint="https://hub.example/hub/api/",
    token="<hub-api-token>",
    user=None,
)
```

Constructor parameters:

- `hub_api_endpoint: str` — base URL of the JupyterHub REST API.
- `token: str` — Bearer token used for JupyterHub requests.
- `user: Optional[str]` — optional default target user reused by all client methods.

Every method that accepts `user` may override the default configured on the client for that individual call.

## User and server information

### `JupyterHubClient.get_user`

```python
client.get_user(
    include_stopped_servers: bool = False,
    user: Optional[str] = None,
) -> dict
```

Returns a JupyterHub user model. When neither the method nor the client specifies a user, the token owner is requested. `include_stopped_servers` asks JupyterHub to include stopped named servers in the returned user model.

### `JupyterHubClient.get_servers`

```python
client.get_servers(
    include_stopped_servers: bool = False,
    user: Optional[str] = None,
) -> dict
```

Returns the `servers` mapping from the selected JupyterHub user model.

## Server lifecycle

### `JupyterHubClient.start_server`

```python
client.start_server(
    server: str,
    options: Optional[Union[str, Mapping[str, Any]]] = None,
    user: Optional[str] = None,
) -> None
```

Starts a named server. Use `server=""` for the default unnamed server. `options` may be a Python mapping or a JSON object string containing spawner options.

### `JupyterHubClient.stop_server`

```python
client.stop_server(
    server: str,
    user: Optional[str] = None,
) -> None
```

Stops a named or default server. Use `server=""` for the default server. A successful stop operation returns `None`; failures raise an exception.

## Sharing

### `JupyterHubClient.add_shared_access`

```python
client.add_shared_access(
    server: str,
    grant_to_user: Optional[str] = None,
    grant_to_group: Optional[str] = None,
    scope: Sequence[str] = (),
    user: Optional[str] = None,
) -> dict
```

Grants access to a server. Exactly one of `grant_to_user` and `grant_to_group` must be provided. `scope` contains optional JupyterHub scopes to grant.

### `JupyterHubClient.remove_shared_access`

```python
client.remove_shared_access(
    server: str,
    remove_from_user: Optional[str] = None,
    remove_from_group: Optional[str] = None,
    scope: Sequence[str] = (),
    remove_all: bool = False,
    user: Optional[str] = None,
) -> Optional[dict]
```

Removes shared access from a server. For a scoped removal, exactly one of `remove_from_user` and `remove_from_group` must be supplied. When `remove_all=True`, the adapter sends the Hub DELETE operation that removes all shares for the server; a successful DELETE returns `None`.

### `JupyterHubClient.list_shared_access`

```python
client.list_shared_access(
    server: str,
    user: Optional[str] = None,
) -> dict
```

Returns sharing information for a server.

## Tokens

### `JupyterHubClient.get_token`

```python
client.get_token(
    api_token_id: str,
    user: Optional[str] = None,
) -> dict
```

Returns one API token model identified by `api_token_id`.

### `JupyterHubClient.add_token`

```python
client.add_token(
    expiration: Optional[int] = None,
    note: Optional[str] = None,
    role: Sequence[str] = (),
    scope: Sequence[str] = (),
    user: Optional[str] = None,
) -> dict
```

Creates a JupyterHub API token. `expiration` is the requested token lifetime in seconds; zero requests a non-expiring token. `note` adds a description. `role` and `scope` are mutually exclusive and may each contain multiple values.

### `JupyterHubClient.delete_token`

```python
client.delete_token(
    api_token_id: str,
    user: Optional[str] = None,
) -> None
```

Deletes the API token identified by `api_token_id`. A successful DELETE returns `None`.

### `JupyterHubClient.list_tokens`

```python
client.list_tokens(
    user: Optional[str] = None,
) -> dict
```

Returns API token information for the selected user.

## Filesystem

### `JupyterHubClient.get_path`

```python
client.get_path(
    server: str,
    path: str,
    show_content: bool = False,
    user: Optional[str] = None,
) -> dict
```

Returns a file or directory model from the Jupyter Contents API. `show_content=True` asks the server to include content in the response.

### `JupyterHubClient.add_path`

```python
client.add_path(
    server: str,
    destination: str,
    path_type: str,
    name: Optional[str] = None,
    copy_from: Optional[str] = None,
    user: Optional[str] = None,
) -> dict
```

Creates a `file` or `directory` at `destination`. `path_type` must therefore be either `"file"` or `"directory"`. `name` optionally renames the newly created object and `copy_from` requests a server-side copy from another path.

### `JupyterHubClient.delete_path`

```python
client.delete_path(
    server: str,
    path: str,
    user: Optional[str] = None,
) -> None
```

Deletes a file or empty directory through the Jupyter Contents API.

### `JupyterHubClient.upload_file`

```python
client.upload_file(
    server: str,
    file: str,
    destination: str,
    user: Optional[str] = None,
) -> dict
```

Reads `file` from the local filesystem, base64-encodes it, and uploads it to `destination` on a running Jupyter server. If `destination` is a directory, the local filename is appended automatically; if it is a file, that file is overwritten.

## Execution

### `JupyterHubClient.exec_command`

```python
client.exec_command(
    server: str,
    command: Sequence[str],
    output: str = "text",
    user: Optional[str] = None,
) -> Union[str, dict]
```

Executes a shell command through the JupyterLab control endpoint. `command` is a sequence of strings; the server-side extension joins the values before executing the resulting command through the shell. With `output="text"`, only the response `output` string is returned. With `output="json"`, the complete JSON response is returned.

This operation requires the `jupyterlab_control_exec` Jupyter Server extension to be installed and enabled in the target single-user server. The extension provides `POST /jlab-control/exec`. It is a server-side deployment prerequisite rather than a normal dependency of the client library. If the endpoint is missing, the adapter raises `JupyterHubNotFoundError` with a message explaining that the extension must be installed and enabled.

For the current provisional extension, see `https://gitlab.cesnet.cz/jaromir.hradil/jupyterlab-control-extension`.

## Functional compatibility API

The original module-level functions remain public for backwards compatibility and for simple one-off calls. Their signatures continue to include `hub_api_endpoint` and `token` explicitly. New integrations should prefer `JupyterHubClient` so common connection parameters are configured once rather than repeated for every operation.

The compatibility functions are:

- `get_user`, `get_servers`;
- `start_server`, `stop_server`;
- `add_shared_access`, `remove_shared_access`, `list_shared_access`;
- `get_token`, `add_token`, `delete_token`, `list_tokens`;
- `get_path`, `add_path`, `delete_path`, `upload_file`;
- `exec_command`.

Everything prefixed with `_` is internal implementation detail and is not part of the supported public API.
