"""Widget signing per W3C XML Digital Signatures for Widgets, as Tizen verifies it.

author-signature.xml covers every file; signature1.xml covers every file plus the
author signature. Both use RSA-SHA512 over an exclusive-C14N SignedInfo with SHA-512
digests. The XML is written directly in canonical form, so the bytes that get hashed
and signed are exactly what a C14N processor derives from the stored document.
"""

import base64
import hashlib
import io
import urllib.parse
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from .certs import Identity
from .package import AUTHOR_SIGNATURE, read_files

DISTRIBUTOR_SIGNATURE = "signature1.xml"

DSIG_NS = "http://www.w3.org/2000/09/xmldsig#"
DSP_NS = "http://www.w3.org/2009/xmldsig-properties"
WIDGETS_DIGSIG = "http://www.w3.org/ns/widgets-digsig"


def sign_package(src: Path, out: Path, author: Identity, distributor: Identity) -> None:
    """Write a signed .wgt built from a source directory or an existing .wgt."""
    files = read_files(src)
    author_signature = _signature("AuthorSignature", files, author)
    distributor_signature = _signature(
        "DistributorSignature", [(AUTHOR_SIGNATURE, author_signature), *files], distributor
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(AUTHOR_SIGNATURE, author_signature)
        archive.writestr(DISTRIBUTOR_SIGNATURE, distributor_signature)
        for name, data in files:
            archive.writestr(name, data)
    out.write_bytes(buffer.getvalue())


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _properties(signature_id: str, *, standalone: bool) -> str:
    """The `#prop` Object. Standalone, it carries the default namespace that it
    inherits from <Signature> in the document, as C14N of the element does."""
    role = "author" if signature_id == "AuthorSignature" else "distributor"
    xmlns = f' xmlns="{DSIG_NS}"' if standalone else ""

    def prop(prop_id: str, element: str, uri: str | None = None) -> str:
        uri_attr = f' URI="{uri}"' if uri else ""
        return (
            f'<SignatureProperty Id="{prop_id}" Target="#{signature_id}">'
            f"<dsp:{element}{uri_attr}></dsp:{element}></SignatureProperty>"
        )

    return (
        f'<Object{xmlns} Id="prop"><SignatureProperties xmlns:dsp="{DSP_NS}">'
        + prop("profile", "Profile", f"{WIDGETS_DIGSIG}#profile")
        + prop("role", "Role", f"{WIDGETS_DIGSIG}#role-{role}")
        + prop("identifier", "Identifier")
        + "</SignatureProperties></Object>"
    )


def _signed_info(files: list[tuple[str, bytes]], properties_digest: str, *, standalone: bool) -> str:
    xmlns = f' xmlns="{DSIG_NS}"' if standalone else ""
    references = "".join(
        f'<Reference URI="{urllib.parse.quote(name, safe="/")}">'
        '<DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha512"></DigestMethod>'
        f"<DigestValue>{_b64(hashlib.sha512(data).digest())}</DigestValue></Reference>"
        for name, data in files
    )
    return (
        f"<SignedInfo{xmlns}>"
        '<CanonicalizationMethod Algorithm="http://www.w3.org/2001/10/xml-exc-c14n#"></CanonicalizationMethod>'
        '<SignatureMethod Algorithm="http://www.w3.org/2001/04/xmldsig-more#rsa-sha512"></SignatureMethod>'
        + references
        + '<Reference URI="#prop"><Transforms>'
        '<Transform Algorithm="http://www.w3.org/2006/12/xml-c14n11"></Transform></Transforms>'
        '<DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha512"></DigestMethod>'
        f"<DigestValue>{properties_digest}</DigestValue></Reference></SignedInfo>"
    )


def _signature(signature_id: str, files: list[tuple[str, bytes]], identity: Identity) -> bytes:
    properties_digest = _b64(hashlib.sha512(_properties(signature_id, standalone=True).encode()).digest())
    signed_info = _signed_info(files, properties_digest, standalone=True).encode()
    value = identity.key.sign(signed_info, padding.PKCS1v15(), hashes.SHA512())

    certificates = ""
    for cert in identity.chain:
        der = _b64(cert.public_bytes(serialization.Encoding.DER))
        wrapped = "\n".join(der[i : i + 76] for i in range(0, len(der), 76))
        certificates += f"<X509Certificate>\n{wrapped}\n</X509Certificate>"

    return (
        f'<Signature xmlns="{DSIG_NS}" Id="{signature_id}">'
        + _signed_info(files, properties_digest, standalone=False)
        + f"<SignatureValue>{_b64(value)}</SignatureValue>"
        + f"<KeyInfo><X509Data>{certificates}</X509Data></KeyInfo>"
        + _properties(signature_id, standalone=False)
        + "</Signature>"
    ).encode()
