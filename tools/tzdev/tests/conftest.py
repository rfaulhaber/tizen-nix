from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from tzdev.certs import DEVELOPER_CA_PASSPHRASE, DISTRIBUTOR_PASSPHRASE


def _issue(subject: str, issuer_name: x509.Name | None, issuer_key, *, ca: bool):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject)])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(issuer_name or name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        .sign(issuer_key or key, hashes.SHA256())
    )
    return key, cert


@pytest.fixture(scope="session")
def tizen_certs(tmp_path_factory) -> Path:
    """A stand-in for the Tizen SDK certificate files, laid out the same way."""
    root = tmp_path_factory.mktemp("tizen-certificates")

    dev_root_key, dev_root = _issue("Test Developers Root", None, None, ca=True)
    dev_ca_key, dev_ca = _issue("Test Developers CA", dev_root.subject, dev_root_key, ca=True)
    (root / "developer").mkdir()
    (root / "developer/tizen-developer-ca.cer").write_bytes(dev_ca.public_bytes(serialization.Encoding.PEM))
    (root / "developer/tizen-developer-ca-privatekey.pem").write_bytes(
        dev_ca_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.BestAvailableEncryption(DEVELOPER_CA_PASSPHRASE),
        )
    )

    dist_root_key, dist_root = _issue("Test Distributor Root", None, None, ca=True)
    dist_ca_key, dist_ca = _issue("Test Distributor CA", dist_root.subject, dist_root_key, ca=True)
    signer_key, signer = _issue("Test Distributor Signer", dist_ca.subject, dist_ca_key, ca=False)
    (root / "distributor").mkdir()
    (root / "distributor/tizen-distributor-signer.p12").write_bytes(
        pkcs12.serialize_key_and_certificates(
            b"signer",
            signer_key,
            signer,
            [dist_ca, dist_root],
            serialization.BestAvailableEncryption(DISTRIBUTOR_PASSPHRASE),
        )
    )
    return root


@pytest.fixture
def app_dir(tmp_path) -> Path:
    app = tmp_path / "app"
    (app / "img").mkdir(parents=True)
    (app / ".git").mkdir()
    (app / "config.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<widget xmlns="http://www.w3.org/ns/widgets" xmlns:tizen="http://tizen.org/ns/widgets" '
        'id="http://example.org/Test" version="1.0.0">'
        '<tizen:application id="TzTestApp1.Test" package="TzTestApp1" required_version="2.3"/>'
        '<content src="index.html"/></widget>\n'
    )
    (app / "index.html").write_text("<!DOCTYPE html><p>hello</p>\n")
    (app / "img/a b&c.png").write_bytes(b"\x89PNG not really")
    (app / ".git/HEAD").write_text("ref: refs/heads/main\n")
    (app / ".DS_Store").write_bytes(b"junk")
    (app / "signature1.xml").write_text("<stale/>")
    return app
