"""A local Ollama server as the hook writer and the art judge.

Every answer is asked for as JSON against a schema, so what comes back either parses into what
was asked or is thrown away. Nothing here raises: a server that is down, slow or talking
nonsense makes for a None, and the caller carries on without a model.
"""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import httpx
from PIL import Image, UnidentifiedImageError

from manhwatok.domain.models import Manhwa
from manhwatok.ports.llm import ArtVerdict

MAX_SIDE = 1024  # a picture's longer side as the model sees it; more only costs time

_HOOK = {
    "type": "object",
    "properties": {"hook": {"type": "string"}},
    "required": ["hook"],
}
_VERDICT = {
    "type": "object",
    "properties": {
        "same_series": {"type": "boolean"},
        "overlays": {"type": "boolean"},
        "quality": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["same_series", "overlays", "quality", "reason"],
}


class Ollama:
    def __init__(
        self,
        url: str,
        model: str,
        client: httpx.Client | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self._owns_client = client is None
        self._client = client or httpx.Client(base_url=url, timeout=timeout)
        self._think = True  # until the model says it has no thinking to turn off

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def hook(self, manhwa: Manhwa, max_len: int) -> str | None:
        description = manhwa.description.strip()
        if not description:
            return None
        genres = ", ".join(manhwa.genres) or "unknown"
        answer = self._ask(
            "Write the one-sentence hook shown under a manhwa's title on a recommendation "
            f"slide. At most {max_len} characters. Say what the story is about and why it is "
            "worth reading, in plain present-tense English. No spoilers past the premise, no "
            "title, no quotes, no emoji, no hashtags, no trailing ellipsis.\n\n"
            f"Title: {manhwa.title}\nGenres: {genres}\nDescription:\n{description}",
            _HOOK,
        )
        hook = answer.get("hook") if answer else None
        if not isinstance(hook, str):
            return None
        return " ".join(hook.split()) or None

    def judge(self, picture: Path, manhwa: Manhwa, reference: Path | None) -> ArtVerdict | None:
        shown = _encoded(picture)
        if shown is None:
            return None
        images = [shown]
        known = _encoded(reference) if reference is not None else None
        if known is not None:
            images.append(known)
        names = ", ".join(dict.fromkeys([manhwa.title, manhwa.romaji, *(manhwa.synonyms or [])]))
        compare = (
            "The second picture is the official cover of that manhwa: compare the characters "
            "and the drawing style against it. "
            if known is not None
            else ""
        )
        answer = self._ask(
            f"The first picture was found by searching for art of the manhwa {names}. "
            f"{compare}Judge the first picture.\n"
            "same_series: is it art of that manhwa, showing its characters?\n"
            "overlays: is anything laid over the art — a watermark, a logo, a caption, speech "
            "bubbles, a border, or several pictures put together as a collage?\n"
            "quality: 0 to 10 — how clean, sharp and well drawn it is; official art scores "
            "high, a blurry scan, a screenshot or a rough edit scores low.\n"
            "reason: a few words.",
            _VERDICT,
            images,
        )
        if not answer:
            return None
        same, overlays, quality = (answer.get(k) for k in ("same_series", "overlays", "quality"))
        if not isinstance(same, bool) or not isinstance(overlays, bool):
            return None
        if isinstance(quality, bool) or not isinstance(quality, (int, float)):
            return None
        return ArtVerdict(
            ok=same and not overlays,
            score=min(10.0, max(0.0, float(quality))),
            reason=str(answer.get("reason") or "").strip(),
        )

    def _ask(self, prompt: str, schema: dict, images: list[str] | None = None) -> dict | None:
        """The model's answer to `prompt` as the object `schema` describes, or None."""
        message: dict = {"role": "user", "content": prompt}
        if images:
            message["images"] = images
        body: dict = {
            "model": self.model,
            "stream": False,
            "format": schema,
            "messages": [message],
        }
        if self._think:
            body["think"] = False
        try:
            resp = self._client.post("/api/chat", json=body)
            if self._think and resp.status_code == 400 and "think" in resp.text:
                self._think = False
                del body["think"]
                resp = self._client.post("/api/chat", json=body)
            if resp.status_code != 200:
                return None
            answer = json.loads(resp.json()["message"]["content"])
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return None
        return answer if isinstance(answer, dict) else None


def _encoded(path: Path) -> str | None:
    """The picture as the model takes it: a base64 PNG no bigger than MAX_SIDE. None when it
    can't be read."""
    try:
        with Image.open(path) as img:
            rgb = img.convert("RGB")
    except (OSError, UnidentifiedImageError):
        return None
    rgb.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    rgb.save(out, format="PNG")
    return base64.b64encode(out.getvalue()).decode("ascii")
