import asyncio
import contextlib
import json
import logging
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# Keyboard mode: keys pressed in the mpv window are forwarded to the app as script messages.
KEY_BINDINGS = "".join(
    [
        "UP script-message easytv next_channel\n",
        "DOWN script-message easytv prev_channel\n",
        "RIGHT script-message easytv next_video\n",
        "i script-message easytv info\n",
        "ENTER script-message easytv info\n",
        "f cycle fullscreen\n",
        "q script-message easytv quit\n",
        "ESC script-message easytv quit\n",
        *(f"{n} script-message easytv goto {n}\n" for n in range(1, 10)),
    ]
)

_TIME_POS_ID = 1
_CONNECT_TIMEOUT = 5.0
_COMMAND_TIMEOUT = 5.0


@dataclass(frozen=True)
class EndOfFile:
    pass


@dataclass(frozen=True)
class VideoError:
    message: str


@dataclass(frozen=True)
class Message:
    args: tuple[str, ...]


@dataclass(frozen=True)
class Closed:
    pass


PlayerEvent = EndOfFile | VideoError | Message | Closed


class Player(Protocol):
    events: asyncio.Queue[PlayerEvent]

    @property
    def position(self) -> float | None: ...

    async def play(self, path: Path, start: float) -> None: ...

    async def show_text(self, text: str, seconds: float) -> None: ...

    async def stop(self) -> None: ...


class MpvError(Exception):
    pass


class MpvPlayer:
    """Drives an mpv process through its JSON IPC socket."""

    def __init__(
        self, *, keyboard: bool, fullscreen: bool = False, extra_args: Sequence[str] = ()
    ) -> None:
        self.events: asyncio.Queue[PlayerEvent] = asyncio.Queue()
        self._keyboard = keyboard
        self._fullscreen = fullscreen
        self._extra_args = list(extra_args)
        self._tmp: tempfile.TemporaryDirectory[str] | None = None
        self._proc: asyncio.subprocess.Process | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._next_id = 1
        self._position: float | None = None
        self._loading = False
        self._entry_id: int | None = None

    @property
    def position(self) -> float | None:
        return self._position

    async def start(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="easytv-")
        tmp = Path(self._tmp.name)
        socket = tmp / "mpv.sock"
        args = [
            "mpv",
            "--idle=yes",
            "--force-window=yes",
            f"--input-ipc-server={socket}",
            "--no-terminal",
            "--keep-open=no",
            "--osc=no",
            "--no-input-default-bindings",
        ]
        if self._keyboard:
            conf = tmp / "input.conf"
            conf.write_text(KEY_BINDINGS, encoding="utf-8")
            args.append(f"--input-conf={conf}")
        if self._fullscreen:
            args.append("--fullscreen")
        args += self._extra_args

        try:
            self._proc = await asyncio.create_subprocess_exec(
                *args, stdin=asyncio.subprocess.DEVNULL
            )
        except FileNotFoundError as e:
            raise MpvError("mpv is not installed") from e

        reader = await self._connect(socket)
        self._reader_task = asyncio.create_task(self._read_loop(reader))
        await self._command("observe_property", _TIME_POS_ID, "time-pos")

    async def play(self, path: Path, start: float) -> None:
        self._position = None
        self._loading = True
        # The `start` option applies to the next loaded file; setting it first works on every
        # mpv version, unlike loadfile's per-file options whose syntax changed in mpv 0.38.
        await self._command("set_property", "start", f"{start:.3f}")
        reply = await self._command("loadfile", str(path), "replace")
        entry = reply.get("playlist_entry_id") if isinstance(reply, dict) else None
        self._entry_id = entry if isinstance(entry, int) else None

    async def show_text(self, text: str, seconds: float) -> None:
        await self._command("show-text", text, int(seconds * 1000))

    async def stop(self) -> None:
        self._position = None
        await self._command("stop")

    async def send_message(self, *args: str) -> None:
        await self._command("script-message", *args)

    async def close(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            with contextlib.suppress(MpvError, ConnectionError, TimeoutError):
                await self._command("quit")
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=3)
            except TimeoutError:
                self._proc.kill()
                await self._proc.wait()
        if self._reader_task is not None:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
        if self._writer is not None:
            self._writer.close()
        if self._tmp is not None:
            self._tmp.cleanup()

    async def _connect(self, socket: Path) -> asyncio.StreamReader:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _CONNECT_TIMEOUT
        while True:
            try:
                reader, self._writer = await asyncio.open_unix_connection(str(socket))
                return reader
            except (FileNotFoundError, ConnectionRefusedError):
                assert self._proc is not None
                if self._proc.returncode is not None:
                    raise MpvError(f"mpv exited with code {self._proc.returncode}") from None
                if loop.time() > deadline:
                    raise MpvError("timed out waiting for the mpv IPC socket") from None
                await asyncio.sleep(0.05)

    async def _command(self, *args: Any) -> Any:
        if self._writer is None:
            raise MpvError("mpv is not running")
        request_id = self._next_id
        self._next_id += 1
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        payload = {"command": list(args), "request_id": request_id}
        self._writer.write(json.dumps(payload).encode() + b"\n")
        try:
            await self._writer.drain()
            return await asyncio.wait_for(future, timeout=_COMMAND_TIMEOUT)
        finally:
            self._pending.pop(request_id, None)

    async def _read_loop(self, reader: asyncio.StreamReader) -> None:
        try:
            while line := await reader.readline():
                try:
                    message = json.loads(line)
                except ValueError:
                    logger.warning("ignoring invalid message from mpv: %r", line)
                    continue
                if "event" in message:
                    self._on_event(message)
                elif "request_id" in message:
                    self._on_reply(message)
        except ConnectionError as e:
            logger.warning("lost connection to mpv: %s", e)
        finally:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(MpvError("mpv connection closed"))
            self.events.put_nowait(Closed())

    def _on_reply(self, message: dict[str, Any]) -> None:
        future = self._pending.get(message["request_id"])
        if future is None or future.done():
            return
        if message.get("error") == "success":
            future.set_result(message.get("data"))
        else:
            future.set_exception(MpvError(str(message.get("error"))))

    def _on_event(self, message: dict[str, Any]) -> None:
        match message["event"]:
            case "property-change" if message.get("id") == _TIME_POS_ID:
                data = message.get("data")
                # Ignore the previous file's last updates while the new one is loading.
                if not self._loading:
                    self._position = float(data) if isinstance(data, int | float) else None
            case "playback-restart":
                self._loading = False
            case "end-file":
                self._on_end_file(message)
            case "client-message":
                self.events.put_nowait(Message(tuple(str(a) for a in message.get("args", []))))

    def _on_end_file(self, message: dict[str, Any]) -> None:
        entry = message.get("playlist_entry_id")
        if self._entry_id is not None and entry is not None and entry != self._entry_id:
            return  # a file we already replaced
        match message.get("reason"):
            case "eof":
                self.events.put_nowait(EndOfFile())
            case "error":
                self.events.put_nowait(VideoError(str(message.get("file_error", "unknown"))))
