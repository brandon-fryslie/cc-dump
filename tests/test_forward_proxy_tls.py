"""Unit tests for forward proxy TLS certificate authority."""

import os
import stat

from cc_dump.pipeline.forward_proxy_tls import (
    ForwardProxyCertificateAuthority,
    _host_cert_stem,
)


def test_host_cert_stem_sanitizes_path_chars():
    stem = _host_cert_stem("../../evil/host")
    assert "/" not in stem
    assert ".." not in stem


def test_ca_and_key_permissions_hardened(tmp_path):
    ca_dir = tmp_path / "forward-proxy-ca"
    ca = ForwardProxyCertificateAuthority(ca_dir=ca_dir)

    key_path = ca_dir / "ca.key"
    cert_path = ca.ca_cert_path

    assert key_path.exists()
    assert cert_path.exists()

    if os.name == "posix":
        assert stat.S_IMODE(os.stat(ca_dir).st_mode) & 0o077 == 0
        assert stat.S_IMODE(os.stat(key_path).st_mode) & 0o077 == 0


def test_generated_leaf_files_stay_in_tmp_dir(tmp_path):
    ca = ForwardProxyCertificateAuthority(ca_dir=tmp_path / "ca")
    ca.ssl_context_for_host("../../tricky-host")

    generated = list(ca._tmp_dir.iterdir())
    assert generated
    assert all(path.parent == ca._tmp_dir for path in generated)
