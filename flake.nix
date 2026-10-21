{
  description = "Tizen TV web app development without Tizen Studio";

  inputs = {
    flake-parts.url = "github:hercules-ci/flake-parts";
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = inputs @ {flake-parts, ...}:
    flake-parts.lib.mkFlake {inherit inputs;} {
      # Samsung publishes sdb only for x86_64 Linux, macOS and Windows.
      systems = ["x86_64-linux"];

      flake.overlays.default = final: _prev: {
        sdb = final.callPackage ./nix/sdb.nix {};
        tizen-certificates = final.callPackage ./nix/tizen-certificates.nix {};
        tzdev = final.callPackage ./nix/tzdev.nix {};
      };

      perSystem = {
        pkgs,
        system,
        ...
      }: {
        _module.args.pkgs = import inputs.nixpkgs {
          inherit system;
          overlays = [inputs.self.overlays.default];
          config.allowUnfreePredicate = pkg:
            builtins.elem (inputs.nixpkgs.lib.getName pkg) [
              "sdb"
              "tizen-certificates"
            ];
        };

        packages = {
          inherit (pkgs) sdb tzdev;
          default = pkgs.tzdev;
        };

        checks = {inherit (pkgs) tzdev;};

        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            sdb
            tzdev
            nodejs
            python3
            zip
            unzip
            openssl
          ];
        };

        formatter = pkgs.alejandra;
      };
    };
}
