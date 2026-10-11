"""The root management command stays a thin, lazy dispatcher."""
from __future__ import annotations

import pytest

import manage


@pytest.mark.parametrize(
    ("argv", "module", "forwarded"),
    [
        (["collect", "kfc"], "competitors.kfc.run_collector", []),
        (
            ["collect", "hardees", "--channel=DELIVERY", "--no-screenshots"],
            "competitors.hardees.run_collector",
            ["--channel=DELIVERY", "--no-screenshots"],
        ),
        (
            ["collect", "hungerstation"],
            "competitors.hungerstation.collector",
            ["--all"],
        ),
        (
            ["collect", "hungerstation", "--brand", "kfc", "--serial", "emulator-5556"],
            "competitors.hungerstation.collector",
            ["--brand", "kfc", "--serial", "emulator-5556"],
        ),
        (["schedule", "burger-king"], "competitors.burger_king.scheduler", []),
        (["schedule", "hungerstation"], "competitors.hungerstation.scheduler", []),
    ],
)
def test_commands_dispatch_without_starting_runtime(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    module: str,
    forwarded: list[str],
) -> None:
    called = []

    def fake_call(module_name: str, options=()) -> int:
        called.append((module_name, list(options)))
        return 0

    monkeypatch.setattr(manage, "_call_main", fake_call)
    assert manage.main(argv) == 0
    assert called == [(module, forwarded)]


def test_unknown_collector_has_argparse_error() -> None:
    with pytest.raises(SystemExit) as error:
        manage.main(["collect", "wendys"])
    assert error.value.code == 2


def test_collect_all_rejects_source_options() -> None:
    with pytest.raises(SystemExit) as error:
        manage.main(["collect", "all", "--channel=PICKUP"])
    assert error.value.code == 2
