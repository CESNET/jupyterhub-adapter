from click.testing import CliRunner

from fedcloud_jupyterhub.cli import jupyterhub


def test_cli_group_loads():
    result = CliRunner().invoke(jupyterhub, ["--help"])

    assert result.exit_code == 0
    assert "Communicate with Jupyterhub" in result.output
    assert "server" in result.output
    assert "token" in result.output


def test_cli_reports_library_validation_errors():
    result = CliRunner().invoke(
        jupyterhub,
        [
            "server",
            "start",
            "--hub-api-endpoint",
            "https://hub.example/api/",
            "--token",
            "token",
            "--server",
            "demo",
            "--options",
            "{broken",
        ],
    )

    assert result.exit_code != 0
    assert "valid JSON" in result.output
