"""Driving a TV in Developer Mode through Samsung's sdb."""

import json
import os
import re
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

from . import TzdevError

DEVICE_PORT = 26101
DEFAULT_TOOLPATH = "/home/owner/share/tmp/sdk_tools"

# Substrings of failed `vd_appinstall` output, and what usually fixes each.
_INSTALL_HINTS = [
    (
        "author certificate not match",
        "This app id is installed under a different author certificate. Uninstall it first.",
    ),
    (
        "invalid certificate chain",
        "The TV rejected the certificate chain. Tizen 8.0+ TVs need a Samsung-issued profile "
        "bound to the TV's DUID (shown by `tzdev info`).",
    ),
    ("not valid yet", "The certificate starts after the TV's clock. Check the TV's date and time."),
    ("unsinged file", "A file in the package isn't covered by the signature. Sign again after the last change."),
]


class Device:
    def __init__(self, address: str, sdb: str = "sdb"):
        host, _, port = address.partition(":")
        self.host = host
        self.serial = f"{host}:{port or DEVICE_PORT}"
        self.sdb = sdb

    def _run(self, *args: str, timeout: float = 120) -> str:
        try:
            result = subprocess.run([self.sdb, *args], capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError as error:
            raise TzdevError(f"{self.sdb} not found on PATH") from error
        except subprocess.TimeoutExpired as error:
            raise TzdevError(f"`sdb {' '.join(args)}` timed out") from error
        output = result.stdout + result.stderr
        if result.returncode != 0:
            raise TzdevError(output.strip() or f"`sdb {' '.join(args)}` failed")
        return output

    def _on_device(self, *args: str, timeout: float = 120) -> str:
        return self._run("-s", self.serial, *args, timeout=timeout)

    def shell(self, *args: str, timeout: float = 120) -> str:
        """Run one of the verbs a retail TV's sdbd allows; it is not a general shell."""
        return self._on_device("shell", "0", *args, timeout=timeout)

    def connect(self) -> None:
        self._start_server()
        if self.devices().get(self.serial, ("",))[0] == "device":
            return
        output = self._run("connect", self.serial)
        if self.devices().get(self.serial, ("",))[0] != "device":
            raise TzdevError(
                f"cannot connect to {self.serial}: {output.strip()}\n"
                "Check that Developer Mode is on with this machine as its Host PC IP, "
                "then restart the TV fully (hold power until the logo appears)."
            )

    def _start_server(self) -> None:
        self._run("start-server")
        # start-server claims success even when the server it spawned died at once, which
        # happens when sdb lives under a path longer than 127 characters: it truncates its
        # own path when re-executing itself.
        port = int(os.environ.get("SDB_SERVER_PORT", "26099"))
        for _ in range(30):
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", port)) == 0:
                    return
            time.sleep(0.1)
        raise TzdevError(f"the sdb server is not listening on port {port}")

    def devices(self) -> dict[str, tuple[str, str]]:
        """Connected devices as serial -> (state, model)."""
        devices = {}
        for line in self._run("devices").splitlines()[1:]:
            fields = line.split()
            if len(fields) >= 2:
                devices[fields[0]] = (fields[1], " ".join(fields[2:]))
        return devices

    def capability(self) -> dict[str, str]:
        capabilities = {}
        for line in self._on_device("capability").splitlines():
            key, sep, value = line.partition(":")
            if sep:
                capabilities[key.strip()] = value.strip()
        return capabilities

    def duid(self) -> str:
        return self.shell("getduid").strip()

    def install(self, wgt: Path, app_id: str) -> None:
        toolpath = self.capability().get("sdk_toolpath", DEFAULT_TOOLPATH)
        # vd_appinstall splits its arguments on whitespace, so the remote name must have none.
        remote = f"{toolpath}/{app_id}.wgt"
        self._on_device("push", str(wgt), remote, timeout=300)
        output = self.shell("vd_appinstall", app_id, remote, timeout=300)
        # vd_appinstall exits 0 whether or not the install worked.
        lowered = output.lower()
        if "install failed" in lowered or "val[fail]" in lowered:
            hints = [hint for needle, hint in _INSTALL_HINTS if needle in lowered]
            failure = [line for line in output.splitlines() if "fail" in line.lower()] or output.splitlines()[-3:]
            raise TzdevError("\n".join(["install failed:", *failure, *hints]))

    def launch(self, app_id: str) -> None:
        output = self.shell("was_execute", app_id)
        if "launched" not in output:
            raise TzdevError(f"launch failed:\n{output.strip()}")

    def terminate(self, app_id: str) -> None:
        self.shell("was_kill", app_id)

    def uninstall(self, app_id: str) -> None:
        output = self.shell("vd_appuninstall", app_id, timeout=300)
        if "fail" in output.lower():
            raise TzdevError(f"uninstall failed:\n{output.strip()}")

    def apps(self) -> list[dict[str, str]]:
        """Installed apps, parsed from vd_applist's `----key = value----` blocks."""
        apps: list[dict[str, str]] = []
        for line in self.shell("vd_applist").splitlines():
            match = re.fullmatch(r"-+(\w+)\s*=(.*?)-+", line.strip())
            if not match:
                continue
            key, value = match.groups()
            if key == "app_id":
                apps.append({})
            if apps:
                apps[-1][key] = value.strip()
        return apps

    def debug(self, app_id: str, local_port: int) -> list[dict]:
        """Relaunch the app with its inspector enabled and forward it to local_port."""
        # The TV reports an inspector port only for a launch that `debug` itself performs.
        self.terminate(app_id)
        # The debug verb sometimes drops the connection; retrying it is safe.
        for _ in range(3):
            output = self.shell("debug", app_id)
            match = re.search(r"port:\s*(\d+)", output)
            if match:
                break
        else:
            raise TzdevError(f"the TV did not report a debug port:\n{output.strip()}")

        try:
            self._on_device("forward", "--remove", f"tcp:{local_port}")
        except TzdevError:
            pass
        self._on_device("forward", f"tcp:{local_port}", f"tcp:{match.group(1)}")

        for _ in range(40):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{local_port}/json", timeout=2) as response:
                    return json.load(response)
            except OSError:
                time.sleep(0.25)
        raise TzdevError(f"the inspector did not answer on 127.0.0.1:{local_port}")

    def stop_server(self) -> None:
        self._run("kill-server")
