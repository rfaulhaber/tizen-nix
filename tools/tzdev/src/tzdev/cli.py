"""tzdev: create signing profiles, then sign, install, launch and debug TV apps."""

import argparse
import getpass
import os
import sys
import tempfile
from pathlib import Path

from . import TzdevError, certs, package, signing
from .device import Device


def default_profile() -> Path:
    if configured := os.environ.get("TZDEV_PROFILE"):
        return Path(configured).expanduser()
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(data_home) / "tzdev" / "profiles" / "default"


def connect(args: argparse.Namespace) -> Device:
    if not args.tv:
        raise TzdevError("no TV address: set TIZEN_TV or pass --tv")
    device = Device(args.tv)
    device.connect()
    return device


def resolve_app(value: str) -> str:
    """Accept an app id, or a path to a source directory, .wgt or config.xml."""
    path = Path(value)
    return package.read_app_id(path) if path.exists() else value


def print_inspector(targets: list[dict], port: int) -> None:
    for target in targets:
        if target.get("type") == "page":
            print(f"DevTools: http://127.0.0.1:{port}{target['devtoolsFrontendUrl']}")
    print(f"Or add 127.0.0.1:{port} to the targets in chrome://inspect.")
    print("Run `tzdev stop` when done: sdb and its forwards listen on every interface.")


def cmd_profile_create(args: argparse.Namespace) -> None:
    tizen_certs = os.environ.get("TZDEV_TIZEN_CERTS")
    if not tizen_certs:
        raise TzdevError("TZDEV_TIZEN_CERTS must point at the Tizen SDK certificates")
    cert = certs.create_profile(args.profile, Path(tizen_certs), args.name, args.email)
    print(f"Created a signing profile in {args.profile}")
    print(f"  author {cert.subject.rfc4514_string()}, valid until {cert.not_valid_after_utc:%Y-%m-%d}")
    print("Back it up: a TV refuses to update an app signed with a different author key.")


def cmd_profile_show(args: argparse.Namespace) -> None:
    author, distributor = certs.load_profile(args.profile)
    print(f"Profile {args.profile}")
    for role, identity in (("author", author), ("distributor", distributor)):
        leaf = identity.chain[0]
        print(f"  {role}: {leaf.subject.rfc4514_string()}")
        print(f"    issued by {leaf.issuer.rfc4514_string()}, valid until {leaf.not_valid_after_utc:%Y-%m-%d}")


def cmd_sign(args: argparse.Namespace) -> None:
    author, distributor = certs.load_profile(args.profile)
    name = args.src.resolve().name
    out = args.output or Path(f"{Path(name).stem if args.src.is_file() else name}.signed.wgt")
    signing.sign_package(args.src, out, author, distributor)
    print(f"Signed {out}")


def cmd_info(args: argparse.Namespace) -> None:
    device = connect(args)
    capabilities = device.capability()
    _, model = device.devices().get(device.serial, ("", ""))
    print(f"{device.serial}  {model}")
    print(f"  Tizen {capabilities.get('platform_version', '?')}, {capabilities.get('cpu_arch', '?')}")
    print(f"  staging directory {capabilities.get('sdk_toolpath', '?')}")
    print(f"  DUID {device.duid()}")


def cmd_install(args: argparse.Namespace) -> None:
    if not package.is_signed(args.wgt):
        raise TzdevError(f"{args.wgt} is not signed; sign it first or use `tzdev deploy`")
    app_id = package.read_app_id(args.wgt)
    connect(args).install(args.wgt, app_id)
    print(f"Installed {app_id}")


def cmd_deploy(args: argparse.Namespace) -> None:
    author, distributor = certs.load_profile(args.profile)
    app_id = package.read_app_id(args.src)
    device = connect(args)
    with tempfile.TemporaryDirectory() as tmp:
        wgt = Path(tmp) / f"{app_id}.wgt"
        signing.sign_package(args.src, wgt, author, distributor)
        device.install(wgt, app_id)
    print(f"Installed {app_id}")
    if args.debug:
        print_inspector(device.debug(app_id, args.port), args.port)
    else:
        device.launch(app_id)
        print(f"Launched {app_id}")


def cmd_launch(args: argparse.Namespace) -> None:
    app_id = resolve_app(args.app)
    connect(args).launch(app_id)
    print(f"Launched {app_id}")


def cmd_debug(args: argparse.Namespace) -> None:
    print_inspector(connect(args).debug(resolve_app(args.app), args.port), args.port)


def cmd_uninstall(args: argparse.Namespace) -> None:
    app_id = resolve_app(args.app)
    connect(args).uninstall(app_id)
    print(f"Uninstalled {app_id}")


def cmd_apps(args: argparse.Namespace) -> None:
    apps = sorted(connect(args).apps(), key=lambda app: app.get("app_title", "").lower())
    width = max((len(app.get("app_tizen_id", "")) for app in apps), default=0)
    for app in apps:
        print(f"{app.get('app_tizen_id', '?'):<{width}}  {app.get('app_title', '')}  {app.get('app_version', '')}")


def cmd_stop(args: argparse.Namespace) -> None:
    Device(args.tv or "").stop_server()
    print("Stopped the sdb server")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tzdev", description=__doc__)
    parser.add_argument(
        "--tv", default=os.environ.get("TIZEN_TV"), help="TV address as host[:port] (default: $TIZEN_TV)"
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=default_profile(),
        help="signing profile directory (default: $TZDEV_PROFILE or ~/.local/share/tzdev/profiles/default)",
    )
    commands = parser.add_subparsers(required=True, metavar="command")

    profile = commands.add_parser("profile", help="manage the signing profile")
    profile_commands = profile.add_subparsers(required=True, metavar="action")
    create = profile_commands.add_parser("create", help="mint a generic author certificate (TVs up to Tizen 7.0)")
    create.add_argument("--name", default=getpass.getuser(), help="author common name (default: your user name)")
    create.add_argument("--email", help="author email address")
    create.set_defaults(func=cmd_profile_create)
    profile_commands.add_parser("show", help="describe the profile's certificates").set_defaults(func=cmd_profile_show)

    sign = commands.add_parser("sign", help="sign a source directory or .wgt")
    sign.add_argument("src", type=Path)
    sign.add_argument("-o", "--output", type=Path, help="output .wgt (default: <name>.signed.wgt here)")
    sign.set_defaults(func=cmd_sign)

    deploy = commands.add_parser("deploy", help="sign, install and launch a source directory or .wgt")
    deploy.add_argument("src", type=Path)
    deploy.add_argument("--debug", action="store_true", help="launch with the web inspector attached")
    deploy.add_argument("--port", type=int, default=9222, help="local inspector port (default: 9222)")
    deploy.set_defaults(func=cmd_deploy)

    install = commands.add_parser("install", help="install an already signed .wgt")
    install.add_argument("wgt", type=Path)
    install.set_defaults(func=cmd_install)

    for name, func, help_text in (
        ("launch", cmd_launch, "launch an installed app"),
        ("uninstall", cmd_uninstall, "uninstall an app"),
        ("debug", cmd_debug, "relaunch an app with the web inspector attached"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("app", help="app id, or a source directory, .wgt or config.xml")
        command.set_defaults(func=func)
        if name == "debug":
            command.add_argument("--port", type=int, default=9222, help="local inspector port (default: 9222)")

    commands.add_parser("info", help="show the TV's platform and DUID").set_defaults(func=cmd_info)
    commands.add_parser("apps", help="list installed apps").set_defaults(func=cmd_apps)
    commands.add_parser("stop", help="stop the sdb server").set_defaults(func=cmd_stop)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except TzdevError as error:
        print(f"tzdev: error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
