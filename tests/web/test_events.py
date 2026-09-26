import json
import threading
import time

import pytest

pytest.importorskip("fastapi")

from manhwatok.web.events import ChangeWatcher, change_probes, sse_stream  # noqa: E402
from manhwatok.web.jobs import EventBus  # noqa: E402
from tests.tui.helpers import make_ctx  # noqa: E402
from tests.unit.fakes import post  # noqa: E402
from tests.web.helpers import client_for  # noqa: E402


def test_the_stream_sends_events_and_pings_and_ends_when_stopped():
    bus, stop = EventBus(), threading.Event()
    stream = sse_stream(bus, stop, heartbeat=0.05)
    assert next(stream) == "retry: 2000\n\n"
    bus.publish("changed", what="posts")
    assert next(stream) == f"event: changed\ndata: {json.dumps({'what': 'posts'})}\n\n"
    assert next(stream) == ": ping\n\n"  # nothing for a while
    stop.set()
    started = time.monotonic()
    with pytest.raises(StopIteration):
        while True:
            next(stream)
    assert time.monotonic() - started < 1.5  # the server's Ctrl-C isn't kept waiting
    assert bus._queues == []  # unsubscribed


def test_the_events_route_streams(tmp_path):
    with client_for(make_ctx(tmp_path)) as client:
        client.app.state.stop.set()  # the stream ends after its first line
        response = client.get("/events")
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text.startswith("retry: 2000")


def test_the_watcher_says_what_changed():
    bus = EventBus()
    q = bus.subscribe()
    values = {"posts": 1, "store": "a"}

    def store():
        if values["store"] is None:
            raise OSError("gone")
        return values["store"]

    watcher = ChangeWatcher(bus, {"posts": lambda: values["posts"], "store": store}, interval=1)
    assert watcher.check() == []  # the first look only remembers
    values["posts"] = 2
    assert watcher.check() == ["posts"]
    assert q.get_nowait() == ("changed", {"what": "posts"})
    values["store"] = None  # a probe that fails counts as a change once
    assert watcher.check() == ["store"]
    assert watcher.check() == []


def test_the_watcher_looks_in_the_background():
    bus = EventBus()
    q = bus.subscribe()
    values = {"posts": 1}
    watcher = ChangeWatcher(bus, {"posts": lambda: values["posts"]}, interval=0.01)
    watcher.start()
    try:
        values["posts"] = 2
        assert q.get(timeout=2) == ("changed", {"what": "posts"})
    finally:
        watcher.stop()


def test_probes_see_a_new_post_and_a_database_write(tmp_path):
    ctx = make_ctx(tmp_path)
    probes = change_probes(ctx)
    before = {name: probe() for name, probe in probes.items()}
    ctx.tools.posts.save(post(id="20260926-0001"))
    assert probes["posts"]() != before["posts"]
    from manhwatok.domain.account import Account

    time.sleep(0.01)
    ctx.store.accounts.add(Account(handle="reads"))
    assert probes["store"]() != before["store"]
