"""Reading widget packages, given as a source directory or a .wgt archive."""

import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from . import TzdevError

TIZEN_NS = "http://tizen.org/ns/widgets"
AUTHOR_SIGNATURE = "author-signature.xml"
_SIGNATURE_FILE = re.compile(r"author-signature\.xml|signature[1-9][0-9]*\.xml")


def is_signature_file(name: str) -> bool:
    """Signature files only count as such at the package root."""
    return _SIGNATURE_FILE.fullmatch(name) is not None


def read_files(src: Path) -> list[tuple[str, bytes]]:
    """Every file in the package except existing signatures, sorted by path.

    Hidden files are skipped when reading a directory so a source tree's .git or
    editor droppings never end up in a package.
    """
    if src.is_dir():
        files = []
        for path in src.rglob("*"):
            relative = path.relative_to(src)
            if path.is_file() and not any(part.startswith(".") for part in relative.parts):
                files.append((relative.as_posix(), path.read_bytes()))
    elif zipfile.is_zipfile(src):
        with zipfile.ZipFile(src) as archive:
            files = [(info.filename, archive.read(info)) for info in archive.infolist() if not info.is_dir()]
    else:
        raise TzdevError(f"{src} is neither a directory nor a .wgt archive")

    files = [(name, data) for name, data in files if not is_signature_file(name)]
    if not any(name == "config.xml" for name, _ in files):
        raise TzdevError(f"{src} has no config.xml at its root")
    return sorted(files)


def is_signed(wgt: Path) -> bool:
    with zipfile.ZipFile(wgt) as archive:
        return AUTHOR_SIGNATURE in archive.namelist()


def app_id(config_xml: bytes) -> str:
    application = ET.fromstring(config_xml).find(f"{{{TIZEN_NS}}}application")
    if application is None or not application.get("id"):
        raise TzdevError("config.xml has no <tizen:application id=...>")
    return application.get("id")


def read_app_id(src: Path) -> str:
    """The application id from a source directory, a .wgt, or a config.xml."""
    try:
        if src.is_dir():
            return app_id((src / "config.xml").read_bytes())
        if src.name == "config.xml":
            return app_id(src.read_bytes())
        with zipfile.ZipFile(src) as archive:
            return app_id(archive.read("config.xml"))
    except (OSError, KeyError, zipfile.BadZipFile) as error:
        raise TzdevError(f"cannot read config.xml from {src}: {error}") from error
