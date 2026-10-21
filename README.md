# tizen-nix

A development environment for Samsung Tizen TV web apps on NixOS that needs no Tizen Studio, Java or Samsung account.

The dev shell provides:

- `sdb`: Samsung's Smart Development Bridge 4.2.36, pinned from download.tizen.org and patched for NixOS.
- `tzdev`: creates a signing profile, then signs, installs, launches and debugs apps ([tools/tzdev](tools/tzdev)).
- `node`, `python3`, `zip`, `unzip` and `openssl` for building apps.

Enter it with `direnv allow`, which loads it into your current shell, or with `nix develop --command nu`. Plain `nix develop` starts bash.

## One-time setup

1. On the TV, open Apps and type `12345`, turn Developer mode on, and enter this machine's IP as the Host PC IP. Then restart the TV fully by holding the power button until the logo appears. A standby toggle doesn't apply the setting.
2. Tell `tzdev` where the TV is, either in `.envrc.local` (untracked, sourced by `.envrc`) as `export TIZEN_TV=192.168.0.65`, or in your shell environment. `tzdev info` confirms the connection.
3. Create your signing profile with `tzdev profile create --name "Your Name"`. It lands in `~/.local/share/tzdev/profiles/default`; set `TZDEV_PROFILE` to keep it elsewhere. Back it up. A TV refuses to update an app signed with a different author key, so losing the key means uninstalling the app and losing its data.

The profile `tzdev` creates is a generic one: an author certificate under the Tizen Developers CA plus the stock Tizen public distributor certificate. TVs accept it up to Tizen 7.0 (2023 models). Tizen 8.0 and later require a Samsung-issued certificate bound to the TV's DUID. Create one with Apps2Samsung (`nix run nixpkgs#apps2samsung`) and point `TZDEV_PROFILE` at the profile directory it writes under `~/.config/Apps2Samsung/Certificate/`. `tzdev` reads the same layout.

## Everyday commands

| Command | What it does |
|---|---|
| `tzdev deploy <dir or .wgt>` | Sign, install and launch |
| `tzdev deploy --debug <dir or .wgt>` | Same, launched with the web inspector |
| `tzdev debug <app>` | Relaunch with the inspector and forward it to `127.0.0.1:9222` |
| `tzdev sign <dir or .wgt> [-o out.wgt]` | Sign only |
| `tzdev install <signed .wgt>` | Install only |
| `tzdev launch <app>`, `tzdev uninstall <app>` | `<app>` is an app id or a path to a source directory, `.wgt` or `config.xml` |
| `tzdev apps`, `tzdev info` | List installed apps; show the TV's Tizen version and DUID |
| `tzdev stop` | Stop the sdb server |

`sdb`'s server (port 26099) and its port forwards listen on every interface, not just localhost, so run `tzdev stop` when you're done.

## Notes for app code

- The TV's web engine is old. Samsung lists the Chromium version for each model year in its [web engine specifications](https://developer.samsung.com/smarttv/develop/specifications/web-engine-specifications.html), e.g. Chrome 76 for 2021 and Chrome 85 for 2022. Transpile to that target and ship classic scripts. Packaged apps load from `file://`, where ES modules don't run.
- Samsung's TV APIs (`tizen.*`, `webapis.*`) exist only in pages packaged with the app, not in pages loaded from a remote URL.
- Tizen's installer exits successfully even when an install fails. `tzdev` reads the output instead and explains the common failures, such as `[118, -11] Author certificate not match`.
- The Tizen Developers CA expires on 2027-01-01. TVs don't appear to enforce expiry, since the stock distributor certificate expired in 2022 and is still accepted, but it's worth checking after that date.

## Using it from another project

Add this flake as an input and build on its shell:

```nix
inputs.tizen-nix.url = "github:rfaulhaber/tizen-nix";

devShells.default = pkgs.mkShell {
  inputsFrom = [inputs.tizen-nix.devShells.${system}.default];
};
```

Or skip the input and run `nix develop /path/to/tizen-nix --command nu` from the other project's directory.

## Tests

`nix build .#tzdev` (or `nix flake check`) runs the test suite. It verifies signatures with `xmlsec1`, an implementation independent of `tzdev`'s.
