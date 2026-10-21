{
  lib,
  stdenvNoCC,
  fetchurl,
  unzip,
}:
# The Tizen Developers CA (with its key) and the stock public distributor certificate,
# which together let anyone mint the generic signing profile that pre-Tizen-8 TVs accept.
stdenvNoCC.mkDerivation (finalAttrs: {
  pname = "tizen-certificates";
  version = "0.1.4";

  src = fetchurl {
    url = "https://download.tizen.org/sdk/tizenstudio/official/binary/certificate-generator_${finalAttrs.version}_ubuntu-64.zip";
    hash = "sha256-RGqlLySSBfStVzFzsCycOKpd4DFgKLd90YnkT9X3WWQ=";
  };

  nativeBuildInputs = [unzip];

  sourceRoot = ".";
  dontConfigure = true;
  dontBuild = true;

  installPhase = ''
    runHook preInstall
    certs=data/tools/certificate-generator/certificates
    install -Dm644 -t $out/share/tizen-certificates/developer \
      $certs/developer/tizen-developer-ca.cer \
      $certs/developer/tizen-developer-ca-privatekey.pem
    install -Dm644 -t $out/share/tizen-certificates/distributor \
      $certs/distributor/tizen-distributor-signer.p12
    runHook postInstall
  '';

  meta = {
    description = "Tizen SDK certificate authorities for generic app signing";
    homepage = "https://download.tizen.org/sdk/tizenstudio/official/";
    license = lib.licenses.unfree;
    platforms = lib.platforms.all;
  };
})
