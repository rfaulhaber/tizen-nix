{
  lib,
  stdenv,
  fetchurl,
  unzip,
  autoPatchelfHook,
}:
stdenv.mkDerivation (finalAttrs: {
  pname = "sdb";
  version = "4.2.36";

  src = fetchurl {
    url = "https://download.tizen.org/sdk/tizenstudio/official/binary/sdb_${finalAttrs.version}_ubuntu-64.zip";
    hash = "sha256-rd+CXhqIap8iDLPSh+dEOMrg/6/lghubrKnU9sfeUSQ=";
  };

  nativeBuildInputs = [
    unzip
    autoPatchelfHook
  ];
  buildInputs = [stdenv.cc.cc.lib];

  sourceRoot = ".";
  dontConfigure = true;
  dontBuild = true;

  installPhase = ''
    runHook preInstall
    install -Dm755 data/tools/sdb $out/bin/sdb
    install -Dm644 data/tools/.sdb-completion.bash $out/share/bash-completion/completions/sdb
    runHook postInstall
  '';

  meta = {
    description = "Samsung Smart Development Bridge for Tizen devices";
    homepage = "https://developer.samsung.com/smarttv/develop/getting-started/using-sdk/tv-device.html";
    license = lib.licenses.unfree;
    sourceProvenance = [lib.sourceTypes.binaryNativeCode];
    platforms = ["x86_64-linux"];
    mainProgram = "sdb";
  };
})
