import pytest

from easytv.player import KEY_BINDINGS
from easytv.remote import Action, Command, parse_message


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (("easytv", "next_channel"), Command(Action.NEXT_CHANNEL)),
        (("easytv", "prev_channel"), Command(Action.PREV_CHANNEL)),
        (("easytv", "next_video"), Command(Action.NEXT_VIDEO)),
        (("easytv", "info"), Command(Action.INFO)),
        (("easytv", "quit"), Command(Action.QUIT)),
        (("easytv", "stop"), Command(Action.STOP)),
        (("easytv", "play"), Command(Action.PLAY)),
        (("easytv", "goto", "3"), Command(Action.GOTO, 3)),
    ],
)
def test_valid_commands(args: tuple[str, ...], expected: Command) -> None:
    assert parse_message(args) == expected


@pytest.mark.parametrize(
    "args",
    [
        (),
        ("easytv",),
        ("other-script", "next_channel"),
        ("easytv", "dance"),
        ("easytv", "goto"),
        ("easytv", "goto", "0"),
        ("easytv", "goto", "-1"),
        ("easytv", "goto", "two"),
    ],
)
def test_invalid_commands(args: tuple[str, ...]) -> None:
    assert parse_message(args) is None


@pytest.mark.parametrize(
    "command", [Command(a) for a in Action if a is not Action.GOTO] + [Command(Action.GOTO, 12)]
)
def test_message_args_round_trip(command: Command) -> None:
    assert parse_message(command.message_args()) == command


def test_every_key_binding_is_a_valid_command() -> None:
    for line in KEY_BINDINGS.splitlines():
        key, command, *args = line.split()
        if command == "script-message":
            assert parse_message(args) is not None, key
