"""Store-and-forward outbox semantics."""

from __future__ import annotations

from pids_edge.publish import Outbox


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def test_outbox_replays_only_fresh_messages_in_order() -> None:
    clock = Clock()
    box = Outbox(limit=10, replay_window_s=3.0, clock=clock)
    box.put("a", b"1")
    clock.t = 2.0
    box.put("a", b"2")
    clock.t = 4.0
    box.put("a", b"3")
    fresh = box.drain()
    assert [m.payload for m in fresh] == [b"2", b"3"]
    assert box.expired == 1
    assert len(box) == 0


def test_outbox_is_bounded_and_counts_evictions() -> None:
    box = Outbox(limit=3, replay_window_s=60.0, clock=Clock())
    for i in range(5):
        box.put("t", str(i).encode())
    assert len(box) == 3
    assert box.evicted == 2
    assert [m.payload for m in box.drain()] == [b"2", b"3", b"4"]
