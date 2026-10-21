{
  lib,
  python3Packages,
  xmlsec,
  sdb,
  tizen-certificates,
}:
python3Packages.buildPythonApplication {
  pname = "tzdev";
  version = "0.1.0";
  pyproject = true;

  src = ../tools/tzdev;

  build-system = [python3Packages.setuptools];
  dependencies = [python3Packages.cryptography];

  nativeCheckInputs = [
    python3Packages.pytestCheckHook
    xmlsec
  ];

  makeWrapperArgs = [
    "--prefix"
    "PATH"
    ":"
    (lib.makeBinPath [sdb])
    "--set-default"
    "TZDEV_TIZEN_CERTS"
    "${tizen-certificates}/share/tizen-certificates"
  ];

  meta = {
    description = "Sign, install, run and debug Samsung Tizen TV web apps without Tizen Studio";
    platforms = sdb.meta.platforms;
    mainProgram = "tzdev";
  };
}
