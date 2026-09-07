"""Exception hierarchy exposed by :mod:`fedcloud_jupyterhub`.

The adapter raises exceptions instead of printing errors and returning ``None``.
This allows applications embedding the library to distinguish validation,
transport, HTTP API, response-format, and local filesystem failures and to
handle or log them according to their own policy.
"""

from typing import Optional


class JupyterHubError(Exception):
    """Base class for all adapter-specific exceptions."""


class JupyterHubValidationError(JupyterHubError, ValueError):
    """Raised when arguments passed to a public adapter function are invalid."""


# Backward-compatible name used by the first standalone adapter revision.
# Keep it as an alias so callers importing JupyterHubClientError continue to
# catch exactly the validation errors they caught before the 1.0 release.
JupyterHubClientError = JupyterHubValidationError


class JupyterHubRequestError(JupyterHubError):
    """Raised when an HTTP request cannot be sent or completed."""


class JupyterHubAPIError(JupyterHubError):
    """Raised when JupyterHub or a proxied Jupyter server returns an HTTP error.

    Args:
        status_code: HTTP status code returned by the remote service.
        message: Human-readable error message derived from the response.
        reason: Optional HTTP reason phrase.
        url: Optional request URL associated with the failure.
    """

    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        reason: Optional[str] = None,
        url: Optional[str] = None,
    ) -> None:
        self.status_code = status_code
        self.message = message
        self.reason = reason
        self.url = url

        details = f"JupyterHub API request failed with HTTP {status_code}: {message}"
        if url:
            details = f"{details} ({url})"
        super().__init__(details)


class JupyterHubAuthenticationError(JupyterHubAPIError):
    """Raised for HTTP 401 and 403 responses from the remote service."""


class JupyterHubNotFoundError(JupyterHubAPIError):
    """Raised when the requested JupyterHub resource does not exist (HTTP 404)."""


class JupyterHubResponseError(JupyterHubError):
    """Raised when a successful HTTP response has an unexpected structure."""


class JupyterHubFileError(JupyterHubError, OSError):
    """Raised when a local file required by an adapter operation cannot be read."""
