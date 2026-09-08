"""Optional Click command-line interface for :mod:`fedcloud_jupyterhub`.

The CLI deliberately contains no JupyterHub business logic. It collects
command-line parameters, creates a :class:`JupyterHubClient` for the requested
Hub, invokes one of its public methods, renders successful output, and
translates library exceptions into Click errors. Keeping this layer thin makes
the object-oriented library API the single recommended integration surface for
both Python applications and command-line users.
"""

import json
from functools import wraps
from typing import Any, Callable

import click

from fedcloud_jupyterhub.client import JupyterHubClient
from fedcloud_jupyterhub.exceptions import JupyterHubError


def jupyterhub_full(method_name: str, **kwargs: Any) -> None:
    """Invoke one public :class:`JupyterHubClient` method for a CLI command.

    ``hub_api_endpoint``, ``token``, and ``user`` describe the client context
    and are consumed when the client object is created. All remaining keyword
    arguments are operation-specific and are forwarded to the selected client
    method. This keeps connection parameters out of individual method calls and
    mirrors the recommended Python API.

    Library exceptions remain structured and catchable for Python callers. At
    the CLI boundary they are converted into :class:`click.ClickException` so
    users receive a concise message and a non-zero process exit status.
    """
    client_kwargs = {
        "hub_api_endpoint": kwargs.pop("hub_api_endpoint"),
        "token": kwargs.pop("token"),
        "user": kwargs.pop("user", None),
    }
    output_format = kwargs.get("output")

    try:
        client = JupyterHubClient(**client_kwargs)
        method = getattr(client, method_name)
        response_output = method(**kwargs)
    except JupyterHubError as exc:
        raise click.ClickException(str(exc)) from exc

    if response_output is None:
        return

    if output_format == "text" and isinstance(response_output, str):
        click.echo(response_output, nl=False)
    else:
        click.echo(json.dumps(response_output, indent=4))


def common_hub_params(func: Callable[..., Any]) -> Callable[..., Any]:
    """Add connection and optional target-user parameters to a CLI command."""

    @click.option(
        "--hub-api-endpoint",
        "-e",
        required=True,
        help="JupyterHub API endpoint, usually ending in /hub/api/.",
    )
    @click.option(
        "--token",
        "-t",
        required=True,
        help="JupyterHub API token.",
    )
    @click.option(
        "--user",
        help="JupyterHub user name. If omitted, the token owner is used.",
    )
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    return wrapper


def server_name(func: Callable[..., Any]) -> Callable[..., Any]:
    """Add the server-name parameter shared by server-specific commands."""

    @click.option(
        "--server",
        required=True,
        help='Jupyter server name. Use --server "" for the default server.',
    )
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    return wrapper


def include_stopped_servers(func: Callable[..., Any]) -> Callable[..., Any]:
    """Add the flag controlling whether stopped named servers are requested."""

    @click.option(
        "--include-stopped-servers",
        is_flag=True,
        default=False,
        help="Include stopped named servers in the user/server model.",
    )
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    return wrapper


def api_token_id(func: Callable[..., Any]) -> Callable[..., Any]:
    """Add the API-token identifier used by token show/remove commands."""

    @click.option("--api-token-id", required=True, help="JupyterHub API token ID.")
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    return wrapper


@click.group()
def jupyterhub() -> None:
    """Communicate with JupyterHub."""


@jupyterhub.group()
def user() -> None:
    """Inspect JupyterHub users."""


@user.command("show")
@include_stopped_servers
@common_hub_params
def show_user(**kwargs: Any) -> None:
    """Show a JupyterHub user model."""
    jupyterhub_full("get_user", **kwargs)


@jupyterhub.group()
def server() -> None:
    """Manage JupyterHub user servers."""


@server.command("list")
@include_stopped_servers
@common_hub_params
def list_servers(**kwargs: Any) -> None:
    """List servers belonging to a JupyterHub user."""
    jupyterhub_full("get_servers", **kwargs)


@server.command("start")
@click.option(
    "--options",
    help="Spawner options as a JSON object, for example a profile or image selection.",
)
@common_hub_params
@server_name
def start_user_server(**kwargs: Any) -> None:
    """Start a named or default JupyterHub server."""
    jupyterhub_full("start_server", **kwargs)


@server.command("stop")
@common_hub_params
@server_name
def stop_user_server(**kwargs: Any) -> None:
    """Stop a named or default JupyterHub server."""
    jupyterhub_full("stop_server", **kwargs)


@jupyterhub.group()
def token() -> None:
    """Manage JupyterHub API tokens."""


@token.command("add")
@click.option(
    "--expiration",
    type=int,
    help="Token lifetime in seconds. Zero requests a non-expiring token.",
)
@click.option("--note", help="Human-readable description of the new token.")
@click.option(
    "--role",
    "-r",
    multiple=True,
    help="Role for the new token. May be repeated and cannot be combined with --scope.",
)
@click.option(
    "--scope",
    "-s",
    multiple=True,
    help="Scope for the new token. May be repeated and cannot be combined with --role.",
)
@common_hub_params
def generate_api_token(**kwargs: Any) -> None:
    """Create a JupyterHub API token."""
    jupyterhub_full("add_token", **kwargs)


@token.command("list")
@common_hub_params
def list_api_tokens(**kwargs: Any) -> None:
    """List API tokens belonging to a user."""
    jupyterhub_full("list_tokens", **kwargs)


@token.command("show")
@common_hub_params
@api_token_id
def show_api_token(**kwargs: Any) -> None:
    """Show one API token by ID."""
    jupyterhub_full("get_token", **kwargs)


@token.command("rm")
@common_hub_params
@api_token_id
def delete_api_token(**kwargs: Any) -> None:
    """Delete one API token by ID."""
    jupyterhub_full("delete_token", **kwargs)


@jupyterhub.group()
def sharing() -> None:
    """Manage JupyterHub server sharing."""


@sharing.command("add")
@click.option(
    "--scope",
    "-s",
    multiple=True,
    help="Scope to grant. May be repeated; Hub defaults apply when omitted.",
)
@click.option(
    "--grant-to-user",
    help="User receiving access. Cannot be combined with --grant-to-group.",
)
@click.option(
    "--grant-to-group",
    help="Group receiving access. Cannot be combined with --grant-to-user.",
)
@server_name
@common_hub_params
def add_sharing(**kwargs: Any) -> None:
    """Grant access to a server."""
    jupyterhub_full("add_shared_access", **kwargs)


@sharing.command("rm")
@click.option(
    "--all",
    "remove_all",
    is_flag=True,
    default=False,
    help="Remove all shared access from the server.",
)
@click.option(
    "--remove-from-user",
    help="User whose access is removed. Cannot be combined with --remove-from-group.",
)
@click.option(
    "--remove-from-group",
    help="Group whose access is removed. Cannot be combined with --remove-from-user.",
)
@click.option(
    "--scope",
    "-s",
    multiple=True,
    help="Scope to remove. May be repeated.",
)
@server_name
@common_hub_params
def remove_sharing(**kwargs: Any) -> None:
    """Remove access from a server."""
    jupyterhub_full("remove_shared_access", **kwargs)


@sharing.command("list")
@server_name
@common_hub_params
def list_sharing(**kwargs: Any) -> None:
    """List server sharing information."""
    jupyterhub_full("list_shared_access", **kwargs)


@jupyterhub.group()
def path() -> None:
    """Manage files and directories through the Jupyter Contents API."""


@path.command("show")
@click.option(
    "--path",
    "-p",
    required=True,
    type=click.Path(readable=False),
    help="Server path to inspect.",
)
@click.option(
    "--show-content",
    is_flag=True,
    default=False,
    help="Include file or directory contents in the response.",
)
@server_name
@common_hub_params
def path_show(**kwargs: Any) -> None:
    """Show a file or directory model."""
    jupyterhub_full("get_path", **kwargs)


@path.command("add")
@click.option(
    "--destination",
    "-d",
    required=True,
    type=click.Path(readable=False),
    help="Server path where the new item is created.",
)
@click.option(
    "--name",
    "-n",
    type=click.Path(readable=False),
    help="Optional final name for the created item.",
)
@click.option(
    "--copy-from",
    type=click.Path(readable=False),
    help="Optional server-side path whose content should be copied.",
)
@click.option(
    "--type",
    "path_type",
    required=True,
    type=click.Choice(["file", "directory"]),
    help="Type of item to create.",
)
@server_name
@common_hub_params
def path_add(**kwargs: Any) -> None:
    """Create a file or directory on a running server."""
    jupyterhub_full("add_path", **kwargs)


@path.command("rm")
@click.option(
    "--path",
    "-p",
    required=True,
    type=click.Path(readable=False),
    help="File or empty-directory path to delete.",
)
@server_name
@common_hub_params
def path_remove(**kwargs: Any) -> None:
    """Delete a file or empty directory from a running server."""
    jupyterhub_full("delete_path", **kwargs)


@jupyterhub.group()
def file() -> None:
    """Upload local files to a running Jupyter server."""


@file.command("add")
@click.option(
    "--file",
    "-f",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Local file to upload.",
)
@click.option(
    "--destination",
    "-d",
    required=True,
    type=click.Path(readable=False),
    help="Existing destination file or directory on the running server.",
)
@server_name
@common_hub_params
def file_add(**kwargs: Any) -> None:
    """Upload or overwrite a file on a running server."""
    jupyterhub_full("upload_file", **kwargs)


@jupyterhub.command("exec")
@click.option(
    "--output",
    "-o",
    default="text",
    type=click.Choice(["json", "text"]),
    help="Output representation returned by the JupyterLab control endpoint.",
)
@click.argument("command", nargs=-1)
@server_name
@common_hub_params
def execute(**kwargs: Any) -> None:
    """Execute a command through the JupyterLab control endpoint."""
    jupyterhub_full("exec_command", **kwargs)
