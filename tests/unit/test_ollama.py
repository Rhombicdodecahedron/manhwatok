import base64
import io
import json

import httpx
from PIL import Image

from manhwatok.adapters.ollama import Ollama
from manhwatok.ports.llm import ArtVerdict
from tests.unit.fakes import manhwa

TITLE = manhwa(
    anilist_id=7,
    title="Tower Climber",
    description="A boy enters a tower.\nHe climbs for years and loses everyone on the way.",
)


class Server:
    """Scripted Ollama: answers each chat with the next reply. A dict is sent as the model's
    JSON answer, a str as its raw text; a Response or an exception is used as it is."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []
        self.paths = []

    def __call__(self, request):
        self.paths.append(request.url.path)
        self.requests.append(json.loads(request.content))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, httpx.Response):
            return reply
        content = reply if isinstance(reply, str) else json.dumps(reply)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})


def _ollama(server, model="tiny"):
    client = httpx.Client(transport=httpx.MockTransport(server), base_url="http://ollama.test")
    return Ollama("http://ollama.test", model, client=client)


def _picture(path, size=(60, 90)):
    Image.new("RGB", size, (200, 30, 30)).save(path)
    return path


def _sizes(request):
    images = request["messages"][-1]["images"]
    return [Image.open(io.BytesIO(base64.b64decode(data))).size for data in images]


# --- hook --------------------------------------------------------------------------------------


def test_hook_is_the_models_sentence_about_the_whole_description():
    server = Server({"hook": "  A boy climbs a tower that takes everyone he loves. "})

    assert _ollama(server).hook(TITLE, 110) == "A boy climbs a tower that takes everyone he loves."

    sent = server.requests[0]
    assert server.paths == ["/api/chat"]
    assert (sent["model"], sent["stream"]) == ("tiny", False)
    assert sent["format"]["required"] == ["hook"]
    asked = sent["messages"][-1]["content"]
    assert "Tower Climber" in asked and "loses everyone on the way" in asked and "110" in asked


def test_hook_is_none_for_a_title_with_no_description():
    server = Server()
    assert _ollama(server).hook(manhwa(description=""), 110) is None
    assert server.requests == []


def test_hook_is_none_when_the_server_is_down():
    assert _ollama(Server(httpx.ConnectError("refused"))).hook(TITLE, 110) is None


def test_hook_is_none_when_the_server_fails():
    assert _ollama(Server(httpx.Response(500, text="boom"))).hook(TITLE, 110) is None


def test_hook_is_none_when_the_answer_is_not_what_was_asked_for():
    assert _ollama(Server("sure! here you go")).hook(TITLE, 110) is None
    assert _ollama(Server({"hook": "   "})).hook(TITLE, 110) is None
    assert _ollama(Server({"other": "x"})).hook(TITLE, 110) is None
    assert _ollama(Server(httpx.Response(200, json={"nothing": 1}))).hook(TITLE, 110) is None


def test_a_model_that_cannot_turn_thinking_off_is_asked_again_without_it():
    refusal = httpx.Response(400, json={"error": '"tiny" does not support thinking'})
    server = Server(refusal, {"hook": "One."}, {"hook": "Two."})
    ollama = _ollama(server)

    assert ollama.hook(TITLE, 110) == "One."
    assert ollama.hook(TITLE, 110) == "Two."

    assert [("think" in r) for r in server.requests] == [True, False, False]


# --- judge -------------------------------------------------------------------------------------


def test_judge_shows_the_picture_then_the_reference_and_reads_the_verdict(tmp_path):
    server = Server({"same_series": True, "overlays": False, "quality": 8, "reason": "clean art"})
    picture = _picture(tmp_path / "pin.png")
    cover = _picture(tmp_path / "cover.png", (30, 40))

    verdict = _ollama(server).judge(picture, TITLE, cover)

    assert verdict == ArtVerdict(ok=True, score=8.0, reason="clean art")
    assert _sizes(server.requests[0]) == [(60, 90), (30, 40)]
    assert "Tower Climber" in server.requests[0]["messages"][-1]["content"]


def test_judge_turns_down_another_series_and_anything_laid_over_the_art(tmp_path):
    picture = _picture(tmp_path / "pin.png")
    other = Server({"same_series": False, "overlays": False, "quality": 9, "reason": "other"})
    marked = Server({"same_series": True, "overlays": True, "quality": 9, "reason": "logo"})

    assert _ollama(other).judge(picture, TITLE, None).ok is False
    assert _ollama(marked).judge(picture, TITLE, None).ok is False


def test_judge_without_a_reference_shows_the_picture_alone(tmp_path):
    server = Server({"same_series": True, "overlays": False, "quality": 5, "reason": ""})
    _ollama(server).judge(_picture(tmp_path / "pin.png"), TITLE, None)
    assert len(server.requests[0]["messages"][-1]["images"]) == 1


def test_judge_sends_big_pictures_scaled_down(tmp_path):
    server = Server({"same_series": True, "overlays": False, "quality": 5, "reason": ""})
    _ollama(server).judge(_picture(tmp_path / "pin.png", (4096, 2048)), TITLE, None)
    assert _sizes(server.requests[0]) == [(1024, 512)]


def test_judge_keeps_the_score_between_0_and_10(tmp_path):
    picture = _picture(tmp_path / "pin.png")
    high = Server({"same_series": True, "overlays": False, "quality": 40, "reason": ""})
    low = Server({"same_series": True, "overlays": False, "quality": -3, "reason": ""})
    assert _ollama(high).judge(picture, TITLE, None).score == 10.0
    assert _ollama(low).judge(picture, TITLE, None).score == 0.0


def test_judge_is_none_when_it_cannot_say(tmp_path):
    picture = _picture(tmp_path / "pin.png")
    (tmp_path / "broken.png").write_bytes(b"not a picture")

    assert _ollama(Server(httpx.ReadTimeout("slow"))).judge(picture, TITLE, None) is None
    assert _ollama(Server({"quality": 7})).judge(picture, TITLE, None) is None
    assert _ollama(Server()).judge(tmp_path / "broken.png", TITLE, None) is None
    assert _ollama(Server()).judge(tmp_path / "missing.png", TITLE, None) is None


def test_an_unreadable_reference_is_left_out_rather_than_failing(tmp_path):
    server = Server({"same_series": True, "overlays": False, "quality": 5, "reason": ""})
    verdict = _ollama(server).judge(_picture(tmp_path / "pin.png"), TITLE, tmp_path / "gone.png")
    assert verdict is not None
    assert len(server.requests[0]["messages"][-1]["images"]) == 1
