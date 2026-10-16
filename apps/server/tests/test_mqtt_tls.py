"""MQTT over TLS (NFR-03): the broker's 8883 listener authenticates itself.

Needs the stack running with certificates (make certs && make up-all); skipped otherwise.
"""

from __future__ import annotations

import shutil
import socket
import ssl
import subprocess
from pathlib import Path

import aiomqtt
import pytest

from pids_server.bus import tls_context
from pids_server.settings import Settings

pytestmark = pytest.mark.integration

CA = Path(__file__).resolve().parents[3] / "infra" / "certs" / "out" / "ca.crt"


def _tls_up() -> bool:
    if not CA.exists():
        return False
    try:
        with socket.create_connection(("127.0.0.1", 8883), timeout=1):
            return True
    except OSError:
        return False


skip_without_tls = pytest.mark.skipif(
    not _tls_up(), reason="no TLS broker (make certs && make up-all)"
)


def _client(settings: Settings, ca: Path, host: str = "localhost") -> aiomqtt.Client:
    return aiomqtt.Client(
        hostname=host,
        port=8883,
        username=settings.mqtt_server_user,
        password=settings.mqtt_server_password.get_secret_value(),
        identifier="pids-tls-test",
        tls_context=tls_context(ca),
        timeout=5,
    )


@skip_without_tls
async def test_tls_listener_verifies_and_authenticates() -> None:
    settings = Settings()
    async with _client(settings, CA) as client:
        await client.subscribe("$SYS/broker/uptime")
        async for msg in client.messages:
            assert msg.topic.matches("$SYS/broker/uptime")
            break


@pytest.fixture
def rogue_ca(tmp_path: Path) -> Path:
    """A self-signed CA that never signed the broker's certificate."""
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("openssl not installed")
    cert = tmp_path / "rogue-ca.crt"
    args = ["req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes"]
    args += [
        "-keyout",
        str(tmp_path / "rogue.key"),
        "-out",
        str(cert),
        "-days",
        "1",
        "-subj",
        "/CN=rogue",
    ]
    subprocess.run([openssl, *args], check=True, capture_output=True)  # noqa: S603 - fixed argv
    return cert


def _handshake(cafile: Path, server_name: str) -> None:
    ctx = ssl.create_default_context(cafile=str(cafile))  # verifies chain + hostname
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    with (
        socket.create_connection(("127.0.0.1", 8883), timeout=3) as raw,
        ctx.wrap_socket(raw, server_hostname=server_name),
    ):
        pass


@skip_without_tls
def test_a_broker_signed_by_another_ca_is_refused(rogue_ca: Path) -> None:
    # same verification the MQTT clients use (ssl default context), with clean teardown
    _handshake(CA, "localhost")  # control: our CA verifies
    with pytest.raises(ssl.SSLCertVerificationError):
        _handshake(rogue_ca, "localhost")


@skip_without_tls
def test_a_name_not_on_the_certificate_is_refused() -> None:
    with pytest.raises(ssl.SSLCertVerificationError):
        _handshake(CA, "attacker.example")
