# Exceptions and logging

The adapter is designed to be embedded in other Python code. It therefore raises exceptions instead of printing errors and returning ambiguous `None` values.

## Exception hierarchy

All adapter-specific failures inherit from `JupyterHubError`:

- `JupyterHubValidationError` — invalid or missing caller input. `JupyterHubClientError` remains as a backward-compatible alias for this exception.
- `JupyterHubRequestError` — a connection, timeout, DNS, TLS, or other `requests` transport failure occurred before a usable HTTP response was received.
- `JupyterHubAPIError` — JupyterHub or a proxied single-user server returned an unsuccessful HTTP response. The exception exposes `status_code`, `message`, `reason`, and `url` attributes.
- `JupyterHubAuthenticationError` — specialization of `JupyterHubAPIError` for HTTP 401 and 403.
- `JupyterHubNotFoundError` — specialization of `JupyterHubAPIError` for HTTP 404.
- `JupyterHubResponseError` — the remote service returned a successful HTTP status but the response body did not have the JSON shape required by the adapter.
- `JupyterHubFileError` — a local upload source could not be read.

Example:

```python
from fedcloud_jupyterhub import (
    JupyterHubAPIError,
    JupyterHubNotFoundError,
    JupyterHubValidationError,
    get_token,
)

try:
    token_model = get_token(
        "https://hub.example/hub/api/",
        "<hub-api-token>",
        api_token_id="123",
    )
except JupyterHubValidationError as exc:
    handle_bad_input(exc)
except JupyterHubNotFoundError:
    token_model = None
except JupyterHubAPIError as exc:
    handle_hub_failure(exc.status_code, exc.message)
```

## Logging policy

The library uses the standard `logging` module under the `fedcloud_jupyterhub` logger namespace. It does not call `logging.basicConfig()` and does not attach handlers, because logging policy belongs to the embedding application.

Applications that want diagnostics can configure logging normally:

```python
import logging

logging.basicConfig(level=logging.INFO)
logging.getLogger("fedcloud_jupyterhub").setLevel(logging.DEBUG)
```

Sensitive values such as API tokens are never included in adapter log messages.
