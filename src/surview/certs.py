"""Certificate Authority management for MITM proxy.

Stable boundary module. Handles CA lifecycle and per-host cert generation.
Thread-safe host cert generation with on-demand signing.
"""

import os
import threading
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


_host_cert_lock = threading.Lock()


def get_state_dir() -> str:
    """Return surview state directory, creating if needed.

    Uses $XDG_STATE_HOME/surview/ (default ~/.local/state/surview/).

    Returns:
        Absolute path to state directory.
    """
    xdg_state = os.environ.get("XDG_STATE_HOME")
    if xdg_state:
        state_dir = os.path.join(xdg_state, "surview")
    else:
        state_dir = os.path.expanduser("~/.local/state/surview")

    os.makedirs(state_dir, exist_ok=True)
    return state_dir


def ensure_ca() -> tuple:
    """Load or generate CA certificate and key.

    Loads from ca.pem/ca.key if they exist, otherwise generates new CA
    with 10-year validity, RSA 2048, BasicConstraints(ca=True).

    Returns:
        Tuple of (cert, key, pem_path) where:
        - cert: Certificate object
        - key: RSAPrivateKey object
        - pem_path: str, absolute path to ca.pem
    """
    state_dir = get_state_dir()
    cert_path = os.path.join(state_dir, "ca.pem")
    key_path = os.path.join(state_dir, "ca.key")

    # Try loading existing CA
    if os.path.exists(cert_path) and os.path.exists(key_path):
        with open(cert_path, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())
        with open(key_path, "rb") as f:
            key = serialization.load_pem_private_key(f.read(), password=None)
        return (cert, key, cert_path)

    # Generate new CA
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "surview MITM CA"),
    ])

    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=3650))  # 10 years
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )

    # Write to disk
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(key_path, "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))

    return (cert, key, cert_path)


def get_host_cert(hostname: str, ca_cert, ca_key) -> str:
    """Get or generate host certificate signed by CA.

    Returns path to certs/<hostname>.pem (cert+key concatenated).
    Generates on cache miss with 1-year validity, SAN DNS:<hostname>.
    Thread-safe via lock.

    Args:
        hostname: DNS hostname for the certificate
        ca_cert: CA certificate object
        ca_key: CA private key object

    Returns:
        Absolute path to host cert file (PEM format, cert+key concatenated).
    """
    state_dir = get_state_dir()
    certs_dir = os.path.join(state_dir, "certs")
    os.makedirs(certs_dir, exist_ok=True)

    cert_path = os.path.join(certs_dir, f"{hostname}.pem")

    # Fast path: cert already exists
    if os.path.exists(cert_path):
        return cert_path

    # Slow path: generate new cert (thread-safe)
    with _host_cert_lock:
        # Double-check after acquiring lock
        if os.path.exists(cert_path):
            return cert_path

        # Generate host key
        host_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        subject = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, hostname),
        ])

        now = datetime.now(timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(ca_cert.subject)
            .public_key(host_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + timedelta(days=365))  # 1 year
            .add_extension(
                x509.SubjectAlternativeName([x509.DNSName(hostname)]),
                critical=False,
            )
            .sign(ca_key, hashes.SHA256())
        )

        # Write cert+key concatenated (format expected by SSLContext)
        with open(cert_path, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
            f.write(host_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            ))

        return cert_path


def check_ca_trusted(ca_pem_path: str) -> bool:
    """Check if CA is trusted by the system.

    macOS: uses `security verify-cert -c <path> -L -q`
    Other platforms: returns False (unknown)

    Args:
        ca_pem_path: Absolute path to CA certificate PEM file

    Returns:
        True if CA is trusted, False otherwise or if unknown.
    """
    import platform
    import subprocess

    if platform.system() != "Darwin":
        return False

    try:
        result = subprocess.run(
            ["security", "verify-cert", "-c", ca_pem_path, "-L", "-q"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def print_trust_instructions(ca_pem_path: str):
    """Print platform-specific instructions for trusting the CA.

    Args:
        ca_pem_path: Absolute path to CA certificate PEM file
    """
    import platform

    system = platform.system()

    if system == "Darwin":
        print("   To trust this CA, run:")
        print(f"      security add-trusted-cert -k ~/Library/Keychains/login.keychain-db {ca_pem_path}")
    elif system == "Linux":
        print("   To trust this CA on Linux:")
        print(f"      sudo cp {ca_pem_path} /usr/local/share/ca-certificates/surview-ca.crt")
        print("      sudo update-ca-certificates")
    else:
        print(f"   To trust this CA, import {ca_pem_path} to your system's certificate store.")
