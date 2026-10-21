"""Signing profiles: an author and a distributor identity, each a key plus its chain."""

import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from . import TzdevError

# These protect files that ship in every Tizen SDK; Samsung publishes them in its
# Apache-2.0 webIDE-common-tizentv library.
DEVELOPER_CA_PASSPHRASE = b"tizencertificatefordevelopercaroqkfwk"
DISTRIBUTOR_PASSPHRASE = b"tizenpkcs12passfordsigner"

# Same layout as Apps2Samsung's profiles, so a Samsung-issued profile it created works as-is.
AUTHOR_P12 = "author.p12"
DISTRIBUTOR_P12 = "distributor.p12"
PASSWORD_FILE = "password.txt"


@dataclass(frozen=True)
class Identity:
    key: rsa.RSAPrivateKey
    # Leaf first, then intermediates. Roots are left out because the TV supplies its own.
    chain: list[x509.Certificate]


def load_identity(p12: bytes, password: bytes) -> Identity:
    key, cert, extra = pkcs12.load_key_and_certificates(p12, password)
    if key is None or cert is None:
        raise TzdevError("PKCS#12 file holds no key and certificate")
    return Identity(key, [cert, *(c for c in extra if c.subject != c.issuer)])


def load_profile(profile: Path) -> tuple[Identity, Identity]:
    """The (author, distributor) identities stored in a profile directory."""
    try:
        password = (profile / PASSWORD_FILE).read_text().strip().encode()
        author = load_identity((profile / AUTHOR_P12).read_bytes(), password)
        distributor = load_identity((profile / DISTRIBUTOR_P12).read_bytes(), password)
    except FileNotFoundError as error:
        raise TzdevError(f"{error.filename} is missing; create a profile with `tzdev profile create`") from error
    except ValueError as error:
        raise TzdevError(f"cannot open the profile in {profile}: {error}") from error
    return author, distributor


def create_profile(profile: Path, tizen_certs: Path, name: str, email: str | None = None) -> x509.Certificate:
    """Mint an author certificate under the Tizen Developers CA, paired with the stock
    Tizen public distributor certificate.

    TVs accept this generic profile up to Tizen 7.0. Tizen 8.0 and later need a
    Samsung-issued profile bound to the TV's DUID instead.
    """
    if (profile / AUTHOR_P12).exists():
        raise TzdevError(f"{profile} already holds an author certificate; refusing to replace it")

    ca_cert = x509.load_pem_x509_certificate((tizen_certs / "developer/tizen-developer-ca.cer").read_bytes())
    ca_key = serialization.load_pem_private_key(
        (tizen_certs / "developer/tizen-developer-ca-privatekey.pem").read_bytes(), DEVELOPER_CA_PASSPHRASE
    )
    distributor = load_identity(
        (tizen_certs / "distributor/tizen-distributor-signer.p12").read_bytes(), DISTRIBUTOR_PASSPHRASE
    )

    now = datetime.now(timezone.utc)
    # Tizen's own generator stops the certificate when its CA expires. TVs have been seen
    # accepting expired certificates, so once the CA has lapsed fall back to a long validity.
    not_after = ca_cert.not_valid_after_utc
    if not_after <= now:
        not_after = now + timedelta(days=3650)

    subject = [x509.NameAttribute(NameOID.COMMON_NAME, name)]
    if email:
        subject.append(x509.NameAttribute(NameOID.EMAIL_ADDRESS, email))

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name(subject))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        # Backdated so a TV whose clock runs behind doesn't reject it as not yet valid.
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(not_after)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=False,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CODE_SIGNING]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )

    password = secrets.token_urlsafe(24).encode()
    profile.mkdir(mode=0o700, parents=True, exist_ok=True)
    _write_private(profile / PASSWORD_FILE, password)
    _write_private(profile / AUTHOR_P12, _to_p12(Identity(key, [cert, ca_cert]), password))
    _write_private(profile / DISTRIBUTOR_P12, _to_p12(distributor, password))
    return cert


def _to_p12(identity: Identity, password: bytes) -> bytes:
    # 3DES/SHA-1 rather than cryptography's AES default, matching the keystores Apps2Samsung
    # writes. Tizen's Java tooling and OpenSSL 3 both read those.
    encryption = (
        serialization.PrivateFormat.PKCS12.encryption_builder()
        .kdf_rounds(2048)
        .key_cert_algorithm(pkcs12.PBES.PBESv1SHA1And3KeyTripleDESCBC)
        .hmac_hash(hashes.SHA1())
        .build(password)
    )
    leaf, *rest = identity.chain
    return pkcs12.serialize_key_and_certificates(b"usercertificate", identity.key, leaf, rest, encryption)


def _write_private(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as file:
        file.write(data)
