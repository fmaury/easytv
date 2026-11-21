"""Query or drive a running EasyTV through mpv's JSON IPC socket, for deploys and diagnosis.

python -m easytv.ctl get path time-pos hwdec-current
python -m easytv.ctl cmd script-message easytv quit
"""

import argparse
import json
import socket
import sys
import tempfile
from pathlib import Path
from typing import Any

_TIMEOUT = 5.0


class CtlError(Exception):
    """No socket, lost connection or command refused by mpv."""


def find_socket(tmp_dir: Path) -> Path:
    """Newest socket created by `MpvPlayer` (a stale one may remain after a crash)."""
    sockets = sorted(tmp_dir.glob("easytv-*/mpv.sock"), key=lambda p: p.stat().st_mtime)
    if not sockets:
        raise CtlError(f"no EasyTV mpv socket in {tmp_dir}: is EasyTV running?")
    return sockets[-1]


class MpvConnection:
    def __init__(self, path: Path) -> None:
        self._sock = socket.socket(socket.AF_UNIX)
        self._sock.settimeout(_TIMEOUT)
        try:
            self._sock.connect(str(path))
        except OSError as e:
            self._sock.close()
            raise CtlError(f"cannot connect to {path}: {e}") from e
        self._file = self._sock.makefile("rb")
        self._next_id = 1
        # Otherwise mpv keeps writing events to us and logs "Broken pipe" once we leave.
        self.command("disable_event", "all")

    def command(self, *args: str) -> Any:
        request_id = self._next_id
        self._next_id += 1
        payload = {"command": list(args), "request_id": request_id}
        try:
            self._sock.sendall(json.dumps(payload).encode() + b"\n")
            for line in self._file:
                message = json.loads(line)
                if message.get("request_id") != request_id:
                    continue  # event or another client's reply
                if message.get("error") != "success":
                    raise CtlError(f"{' '.join(args)}: {message.get('error')}")
                return message.get("data")
        except OSError as e:
            raise CtlError(f"lost connection to mpv: {e}") from e
        raise CtlError("mpv closed the connection")

    def close(self) -> None:
        self._file.close()
        self._sock.close()


def _format(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m easytv.ctl", description=__doc__)
    parser.add_argument("--socket", type=Path, help="mpv socket (default: newest EasyTV one)")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("get", help="print properties as name=value").add_argument(
        "properties", nargs="+"
    )
    sub.add_parser("cmd", help="run an mpv command").add_argument("command", nargs="+")
    args = parser.parse_args(argv)

    failed = False
    try:
        conn = MpvConnection(args.socket or find_socket(Path(tempfile.gettempdir())))
        try:
            if args.action == "get":
                for name in args.properties:
                    try:
                        value = _format(conn.command("get_property", name))
                    except CtlError as e:
                        value, failed = f"<{e}>", True
                    sys.stdout.write(f"{name}={value}\n")
            else:
                result = conn.command(*args.command)
                if result is not None:
                    sys.stdout.write(_format(result) + "\n")
        finally:
            conn.close()
    except CtlError as e:
        sys.stderr.write(f"error: {e}\n")
        return 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
