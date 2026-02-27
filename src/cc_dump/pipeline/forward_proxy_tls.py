"""Forward-proxy TLS certificate authority for CONNECT interception.

// [LAW:one-source-of-truth] CA lifecycle and per-host cert generation live here.
// [LAW:single-enforcer] Certificate trust boundary enforced at this single module.

This module is STABLE — holds crypto state, never hot-reloaded.
"""

from __future__ import annotations

import atexit
import datetime
import hashlib
import ipaddress
import logging
import os
import re
import shutil
import ssl
import tempfile
import threading
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

logger = logging.getLogger(__name__)

_CA_KEY_SIZE = 2048
_HOST_KEY_SIZE = 2048
_CA_VALIDITY_DAYS = 365 * 3
_HOST_VALIDITY_DAYS = 365


class ForwardProxyCertificateAuthority:
    """Generate and cache per-host TLS certificates for forward proxy CONNECT."""

    def __init__(self, ca_dir: Path | None = None) -> None:
        self._ca_dir = ca_dir or Path.home() / ".cc-dump" / "forward-proxy-ca"
        self._ca_dir.mkdir(parents=True, exist_ok=True)
        # [LAW:single-enforcer] CA directory permission hardening is enforced here.
        self._set_permissions(self._ca_dir, 0o700)
        self._ca_key, self._ca_cert = self._load_or_create_ca()
        self._host_contexts: dict[str, ssl.SSLContext] = {}
        self._lock = threading.Lock()
        self._tmp_dir = Path(tempfile.mkdtemp(prefix="cc-dump-forward-proxy-"))
        atexit.register(shutil.rmtree, str(self._tmp_dir), True)

    @property
    def ca_cert_path(self) -> Path:
        """Path to CA certificate PEM file (for NODE_EXTRA_CA_CERTS etc.)."""
        return self._ca_dir / "ca.crt"

    def ssl_context_for_host(self, hostname: str) -> ssl.SSLContext:
        """Return a server-side SSL context presenting a cert for *hostname*."""
        with self._lock:
            ctx = self._host_contexts.get(hostname)
            if ctx is not None:
                return ctx
            ctx = self._create_host_context(hostname)
            self._host_contexts[hostname] = ctx
            return ctx

    # -- private ----------------------------------------------------------

    def _load_or_create_ca(self) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
        key_path = self._ca_dir / "ca.key"
        cert_path = self.ca_cert_path
        if key_path.exists() and cert_path.exists():
            key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
            cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
            self._set_permissions(key_path, 0o600)
            self._set_permissions(cert_path, 0o644)
            logger.info("Loaded existing forward proxy CA from %s", self._ca_dir)
            return key, cert  # type: ignore[return-value]

        key = rsa.generate_private_key(public_exponent=65537, key_size=_CA_KEY_SIZE)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "cc-dump Forward Proxy CA")])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=_CA_VALIDITY_DAYS))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256())
        )
        key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        self._set_permissions(key_path, 0o600)
        self._set_permissions(cert_path, 0o644)
        logger.info("Generated new forward proxy CA at %s", self._ca_dir)
        return key, cert

    def _create_host_context(self, hostname: str) -> ssl.SSLContext:
        key = rsa.generate_private_key(public_exponent=65537, key_size=_HOST_KEY_SIZE)
        now = datetime.datetime.now(datetime.timezone.utc)
        normalized_hostname = _normalize_hostname(hostname)
        cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, normalized_hostname)]))
            .issuer_name(self._ca_cert.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=_HOST_VALIDITY_DAYS))
            .add_extension(
                x509.SubjectAlternativeName([_subject_alt_name(normalized_hostname)]),
                critical=False,
            )
            .sign(self._ca_key, hashes.SHA256())
        )

        # ssl.SSLContext.load_cert_chain requires file paths.
        cert_stem = _host_cert_stem(normalized_hostname)
        cert_path = self._tmp_dir / "{}.crt".format(cert_stem)
        key_path = self._tmp_dir / "{}.key".format(cert_stem)
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        self._set_permissions(key_path, 0o600)
        self._set_permissions(cert_path, 0o644)

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(cert_path), str(key_path))
        return ctx

    def _set_permissions(self, path: Path, mode: int) -> None:
        """Best-effort chmod for private key/cert artifacts."""
        try:
            os.chmod(path, mode)
        except OSError:
            logger.debug("Unable to set permissions for %s", path, exc_info=True)


def _normalize_hostname(hostname: str) -> str:
    raw = str(hostname or "").strip()
    if not raw:
        return "localhost"
    candidate = raw.strip("[]")
    try:
        return candidate.encode("idna").decode("ascii")
    except UnicodeError:
        return candidate


def _host_cert_stem(hostname: str) -> str:
    normalized = _normalize_hostname(hostname)
    visible = re.sub(r"[^A-Za-z0-9_.-]", "_", normalized).strip("._-")
    visible = visible[:48] if visible else "host"
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return "{}-{}".format(visible, digest)


def _subject_alt_name(hostname: str):
    try:
        return x509.IPAddress(ipaddress.ip_address(hostname))
    except ValueError:
        return x509.DNSName(hostname)
