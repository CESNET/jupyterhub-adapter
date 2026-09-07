# Changelog

## 1.0.0

- Make `JupyterHubClient` the recommended public API and update the CLI and documentation to use its methods.
- Document `jupyterlab_control_exec` as the server-side prerequisite for command execution and provide a targeted error when its endpoint is unavailable.

- Provide a standalone Python library for JupyterHub adapter operations.
- Expose explicit, typed parameters for all public library functions.
- Add a reusable `JupyterHubClient` convenience class.
- Raise structured exceptions for validation, transport, HTTP API, response, and local file failures.
- Use Python logging instead of printing errors from library code.
- Keep the Click CLI as an optional thin wrapper over the public library API.
- Add public API documentation, packaging metadata, tests, and release tooling configuration.
