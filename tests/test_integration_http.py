"""Local HTTP integration tests for the public JupyterHub adapter API."""

import base64
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from fedcloud_jupyterhub import JupyterHubClient


class FakeJupyterHubHandler(BaseHTTPRequestHandler):
    """Small stateful HTTP service implementing the routes used by the adapter."""

    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):  # noqa: A002
        """Disable noisy access logging during pytest runs."""

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return None
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_empty(self, status=204):
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _require_auth(self):
        if self.headers.get("Authorization") != "Bearer integration-token":
            self._send_json(403, {"message": "Forbidden"})
            return False
        return True

    def _user_model(self):
        return {
            "name": "alice",
            "servers": self.server.state["servers"],
        }

    def do_GET(self):  # noqa: N802
        if not self._require_auth():
            return

        parsed = urlsplit(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        self.server.state["requests"].append(("GET", path, query, None))

        if path in {"/hub/api/user", "/hub/api/users/alice"}:
            self._send_json(200, self._user_model())
            return

        if path == "/hub/api/users/alice/tokens":
            self._send_json(
                200,
                {"api_tokens": list(self.server.state["tokens"].values())},
            )
            return

        if path.startswith("/hub/api/users/alice/tokens/"):
            token_id = path.rsplit("/", 1)[-1]
            token = self.server.state["tokens"].get(token_id)
            if token is None:
                self._send_json(404, {"message": "Token not found"})
            else:
                self._send_json(200, token)
            return

        if path == "/hub/api/shares/alice/demo":
            self._send_json(
                200,
                {"shares": self.server.state["shares"]},
            )
            return

        prefix = "/user/alice/demo/api/contents/"
        if path.startswith(prefix):
            content_path = path[len(prefix) :]
            model = self.server.state["contents"].get(content_path)

            if model is None:
                self._send_json(404, {"message": "Path not found"})
            else:
                self._send_json(200, model)
            return

        self._send_json(
            404,
            {"message": f"Unhandled GET route: {path}"},
        )

    def do_POST(self):  # noqa: N802
        if not self._require_auth():
            return

        path = urlsplit(self.path).path
        data = self._read_json()

        self.server.state["requests"].append(("POST", path, {}, data))

        if path.startswith("/hub/api/users/alice/servers/"):
            server_name = path.rsplit("/", 1)[-1]

            self.server.state["servers"][server_name] = {
                "url": f"/user/alice/{server_name}/"
            }

            self._send_empty(201)
            return

        if path == "/hub/api/users/alice/tokens":
            token_id = str(self.server.state["next_token_id"])
            self.server.state["next_token_id"] += 1

            token = {
                "id": token_id,
                "token": f"generated-{token_id}",
                "note": (data or {}).get("note"),
            }

            self.server.state["tokens"][token_id] = token
            self._send_json(201, token)
            return

        if path == "/hub/api/shares/alice/demo":
            share = dict(data or {})
            self.server.state["shares"].append(share)
            self._send_json(201, share)
            return

        prefix = "/user/alice/demo/api/contents/"
        if path.startswith(prefix):
            destination = path[len(prefix) :]
            item_type = (data or {}).get("type", "file")

            default_name = (
                "Untitled Folder" if item_type == "directory" else "untitled.txt"
            )

            created_path = (f"{destination.rstrip('/')}/{default_name}").lstrip("/")

            model = {
                "path": created_path,
                "type": item_type,
            }

            self.server.state["contents"][created_path] = model
            self._send_json(201, model)
            return

        if path == "/user/alice/demo/jlab-control/exec":
            command = (data or {}).get("command", [])

            self._send_json(
                200,
                {
                    "output": " ".join(command) + "\n",
                    "return_code": 0,
                },
            )
            return

        self._send_json(
            404,
            {"message": f"Unhandled POST route: {path}"},
        )

    def do_PATCH(self):  # noqa: N802
        if not self._require_auth():
            return

        path = urlsplit(self.path).path
        data = self._read_json()

        self.server.state["requests"].append(("PATCH", path, {}, data))

        if path == "/hub/api/shares/alice/demo":
            self._send_json(200, dict(data or {}))
            return

        prefix = "/user/alice/demo/api/contents/"
        if path.startswith(prefix):
            old_path = path[len(prefix) :]
            new_path = (data or {}).get("path")

            old_model = self.server.state["contents"].pop(
                old_path,
                {"type": "directory"},
            )

            model = {
                "path": new_path,
                "type": old_model.get("type", "directory"),
            }

            self.server.state["contents"][new_path] = model
            self._send_json(200, model)
            return

        self._send_json(
            404,
            {"message": f"Unhandled PATCH route: {path}"},
        )

    def do_PUT(self):  # noqa: N802
        if not self._require_auth():
            return

        path = urlsplit(self.path).path
        data = self._read_json()

        self.server.state["requests"].append(("PUT", path, {}, data))

        prefix = "/user/alice/demo/api/contents/"
        if path.startswith(prefix):
            content_path = path[len(prefix) :]

            model = {
                "path": content_path,
                "type": "file",
            }

            self.server.state["contents"][content_path] = model
            self.server.state["last_upload"] = data

            self._send_json(201, model)
            return

        self._send_json(
            404,
            {"message": f"Unhandled PUT route: {path}"},
        )

    def do_DELETE(self):  # noqa: N802
        if not self._require_auth():
            return

        path = urlsplit(self.path).path

        self.server.state["requests"].append(("DELETE", path, {}, None))

        if path.startswith("/hub/api/users/alice/servers/"):
            server_name = path.rsplit("/", 1)[-1]
            self.server.state["servers"].pop(server_name, None)
            self._send_empty()
            return

        if path.startswith("/hub/api/users/alice/tokens/"):
            token_id = path.rsplit("/", 1)[-1]
            self.server.state["tokens"].pop(token_id, None)
            self._send_empty()
            return

        if path == "/hub/api/shares/alice/demo":
            self.server.state["shares"].clear()
            self._send_empty()
            return

        prefix = "/user/alice/demo/api/contents/"
        if path.startswith(prefix):
            content_path = path[len(prefix) :]
            self.server.state["contents"].pop(
                content_path,
                None,
            )
            self._send_empty()
            return

        self._send_json(
            404,
            {"message": f"Unhandled DELETE route: {path}"},
        )


@contextmanager
def fake_jupyterhub():
    """Run the fake Hub on an ephemeral localhost port for one test."""

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        FakeJupyterHubHandler,
    )

    server.state = {
        "requests": [],
        "servers": {
            "demo": {
                "url": "/user/alice/demo/",
            }
        },
        "tokens": {},
        "next_token_id": 1,
        "shares": [],
        "contents": {
            "work": {
                "path": "work",
                "type": "directory",
            },
        },
        "last_upload": None,
    }

    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
    )

    thread.start()

    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_public_api_against_local_http_server(tmp_path):
    """Exercise all public operation groups through real localhost HTTP requests."""

    with fake_jupyterhub() as server:
        hub_api = f"http://127.0.0.1:{server.server_port}/hub/api/"

        client = JupyterHubClient(
            hub_api,
            "integration-token",
        )

        # User and server information.
        user = client.get_user(include_stopped_servers=True)

        assert user["name"] == "alice"
        assert "demo" in client.get_servers()

        # Server lifecycle.
        client.start_server(
            "new",
            options={"profile": "small"},
        )

        assert "new" in client.get_servers(include_stopped_servers=True)

        client.stop_server("new")

        assert "new" not in client.get_servers(include_stopped_servers=True)

        # Sharing.
        share = client.add_shared_access(
            "demo",
            grant_to_user="bob",
            scope=("access:servers",),
        )

        assert share["user"] == "bob"
        assert client.list_shared_access("demo")["shares"]

        client.remove_shared_access(
            "demo",
            remove_all=True,
        )

        assert client.list_shared_access("demo")["shares"] == []

        # API tokens.
        token = client.add_token(
            expiration=3600,
            note="integration",
        )

        token_id = token["id"]

        assert client.get_token(token_id)["note"] == "integration"

        assert client.list_tokens()["api_tokens"]

        client.delete_token(token_id)

        assert client.list_tokens()["api_tokens"] == []

        # Jupyter Contents API.
        assert (
            client.get_path(
                "demo",
                "work",
            )["type"]
            == "directory"
        )

        created = client.add_path(
            "demo",
            destination="work",
            path_type="directory",
            name="results",
        )

        assert created == {
            "path": "work/results",
            "type": "directory",
        }

        # Upload through a real PUT request.
        local_file = tmp_path / "hello.txt"
        local_file.write_bytes(b"hello")

        uploaded = client.upload_file(
            "demo",
            file=str(local_file),
            destination="work",
        )

        assert uploaded["path"] == "work/hello.txt"

        assert server.state["last_upload"]["content"] == base64.b64encode(
            b"hello"
        ).decode("ascii")

        client.delete_path(
            "demo",
            "work/results",
        )

        assert "work/results" not in server.state["contents"]

        # Command execution endpoint.
        output = client.exec_command(
            "demo",
            ("echo", "hello"),
        )

        assert output == "echo hello\n"

        # Make sure real HTTP requests were made.
        assert server.state["requests"]

        assert all(
            request[1].startswith(
                (
                    "/hub/api/",
                    "/user/alice/",
                )
            )
            for request in server.state["requests"]
        )
