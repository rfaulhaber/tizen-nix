"""Signatures are verified with xmlsec1, independently of how signing.py writes them."""

import base64
import shutil
import subprocess
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest
from cryptography import x509

from tzdev import TzdevError
from tzdev.certs import create_profile, load_profile
from tzdev.package import read_app_id
from tzdev.signing import sign_package

DS = "http://www.w3.org/2000/09/xmldsig#"
CONTENT = {"config.xml", "index.html", "img/a b&c.png"}


def xmlsec_verifies(package_dir: Path, signature_file: str) -> bool:
    xmlsec1 = shutil.which("xmlsec1")
    assert xmlsec1, "xmlsec1 is needed to verify signatures"
    # Run inside the extracted package so the relative file references resolve.
    result = subprocess.run(
        [xmlsec1, "--verify", "--insecure", "--enabled-key-data", "x509", "--id-attr:Id", "Object", signature_file],
        cwd=package_dir,
        capture_output=True,
    )
    return result.returncode == 0


def covered_files(signature_xml: bytes) -> set[str]:
    references = ET.fromstring(signature_xml).iter(f"{{{DS}}}Reference")
    return {urllib.parse.unquote(ref.get("URI")) for ref in references if ref.get("URI") != "#prop"}


def signing_certificate(signature_xml: bytes) -> x509.Certificate:
    der = ET.fromstring(signature_xml).find(f".//{{{DS}}}X509Certificate").text
    return x509.load_der_x509_certificate(base64.b64decode(der))


def extract(wgt: Path, into: Path) -> Path:
    with zipfile.ZipFile(wgt) as archive:
        archive.extractall(into)
    return into


@pytest.fixture
def profile(tmp_path, tizen_certs):
    create_profile(tmp_path / "profile", tizen_certs, "Test Author")
    return load_profile(tmp_path / "profile")


def test_signs_every_file_once_with_both_roles(tmp_path, app_dir, profile):
    sign_package(app_dir, tmp_path / "app.wgt", *profile)
    package = extract(tmp_path / "app.wgt", tmp_path / "extracted")

    names = {path.relative_to(package).as_posix() for path in package.rglob("*") if path.is_file()}
    assert names == CONTENT | {"author-signature.xml", "signature1.xml"}

    author = (package / "author-signature.xml").read_bytes()
    distributor = (package / "signature1.xml").read_bytes()
    assert covered_files(author) == CONTENT
    assert covered_files(distributor) == CONTENT | {"author-signature.xml"}
    assert b"#role-author" in author and b"#role-distributor" in distributor
    assert xmlsec_verifies(package, "author-signature.xml")
    assert xmlsec_verifies(package, "signature1.xml")


def test_tampering_breaks_verification(tmp_path, app_dir, profile):
    sign_package(app_dir, tmp_path / "app.wgt", *profile)
    package = extract(tmp_path / "app.wgt", tmp_path / "extracted")
    (package / "index.html").write_text("<p>changed after signing</p>")
    assert not xmlsec_verifies(package, "author-signature.xml")


def test_resigning_a_wgt_replaces_its_signatures(tmp_path, app_dir, profile, tizen_certs):
    sign_package(app_dir, tmp_path / "first.wgt", *profile)
    create_profile(tmp_path / "other", tizen_certs, "Other Author")
    other_author, other_distributor = load_profile(tmp_path / "other")
    sign_package(tmp_path / "first.wgt", tmp_path / "second.wgt", other_author, other_distributor)

    package = extract(tmp_path / "second.wgt", tmp_path / "extracted")
    assert covered_files((package / "author-signature.xml").read_bytes()) == CONTENT
    assert xmlsec_verifies(package, "author-signature.xml")
    assert signing_certificate((package / "author-signature.xml").read_bytes()) == other_author.chain[0]


def test_profile_author_chain(tmp_path, tizen_certs):
    cert = create_profile(tmp_path / "profile", tizen_certs, "Test Author", "author@example.org")
    author, distributor = load_profile(tmp_path / "profile")

    assert [c.subject.rfc4514_string() for c in author.chain] == [
        cert.subject.rfc4514_string(),
        "CN=Test Developers CA",
    ]
    assert [c.subject.rfc4514_string() for c in distributor.chain] == [
        "CN=Test Distributor Signer",
        "CN=Test Distributor CA",
    ]
    usage = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert x509.oid.ExtendedKeyUsageOID.CODE_SIGNING in usage
    assert not cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    assert (tmp_path / "profile/author.p12").stat().st_mode & 0o077 == 0


def test_refuses_to_replace_an_author_key(tmp_path, tizen_certs):
    create_profile(tmp_path / "profile", tizen_certs, "Test Author")
    with pytest.raises(TzdevError, match="refusing"):
        create_profile(tmp_path / "profile", tizen_certs, "Test Author")


def test_reads_app_id_from_directory_and_wgt(tmp_path, app_dir, profile):
    sign_package(app_dir, tmp_path / "app.wgt", *profile)
    assert read_app_id(app_dir) == read_app_id(tmp_path / "app.wgt") == "TzTestApp1.Test"


def test_rejects_package_without_config(tmp_path, profile):
    (tmp_path / "empty").mkdir()
    (tmp_path / "empty/index.html").write_text("hi")
    with pytest.raises(TzdevError, match="config.xml"):
        sign_package(tmp_path / "empty", tmp_path / "out.wgt", *profile)
