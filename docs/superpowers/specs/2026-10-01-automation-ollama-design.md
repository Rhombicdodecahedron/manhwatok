# Hands-off posting: Ollama hooks, judged art, and `manhwatok auto`

## Goal
An account's plan keeps itself filled, and (for accounts that opt in) posts go out at their
slot without anyone at the keyboard. Along the way two "first thing that passes" steps become
"best of several": the hook under each title is written by a local model instead of being the
description's first sentence cut at 110 characters, and the picture a source fills a title
with is the best of several candidates, as a local vision model judges them.

Everything a model does has today's behaviour as its fallback: with Ollama off or
unreachable, a build still succeeds exactly as before.

## 1. Ollama

### Settings
| Setting | Env | Default |
|---------|-----|---------|
| `ollama_url` | `MANHWATOK_OLLAMA_URL` | `http://127.0.0.1:11434` |
| `ollama_model` | `MANHWATOK_OLLAMA_MODEL` | `gemma4:e2b-mlx`; `off` disables it |
| `ollama_timeout` | — | 120 s |

The test suite sets `MANHWATOK_OLLAMA_MODEL=off` (autouse), so no test reaches a real server.

### Ports (`ports/llm.py`)
```python
class HookWriter(Protocol):
    def hook(self, manhwa: Manhwa, max_len: int) -> str | None: ...

class ArtVerdict(NamedTuple):
    ok: bool        # the right series, and nothing laid over the art
    score: float    # 0–10, how good the art is
    reason: str

class ArtJudge(Protocol):
    def judge(self, picture: Path, manhwa: Manhwa, reference: Path | None) -> ArtVerdict | None: ...
```
`None` means "couldn't say" (server down, timeout, a reply that doesn't parse) and is never an
error: callers fall back.

### Adapter (`adapters/ollama.py`)
One `Ollama(url, model, client=None, timeout=120.0)` implements both ports over `httpx`, with
an injectable client and `close()` like the other adapters.
- `POST /api/chat` with `stream: false`, `think: false` and `format` set to a JSON schema.
- Pictures go base64 in `images`, scaled down to 1024 px on the longer side first.
- `model` is public, since cache keys carry it.

`container.build_llm(settings)` returns `None` when the model is `off`. `PostTools` gains
`writer`, `judge` and `cache`, all optional; `build_post_tools` fills them.

### Hooks (`app/hooks.py`)
`hook_for(manhwa, tools) -> str`: the cached hook, else one the writer makes, else
`first_sentence(manhwa.description)`.
- A written hook is kept only when it is a single line of at most `HOOK_MAX` (110)
  characters with no ellipsis. A longer one is asked for once more; then the fallback.
- Kept in the `Cache` table as `hook:<anilist_id>:<model>`: a title has one hook, written once.
- A fallback is never cached, so a title gets a written hook once the server is back.
- `prefill_items(candidates, tools)` uses it, which covers `next`, `plan fill`, `build` and
  the web's new-post form. Candidate lists that show a hook for every search result keep
  `first_sentence`: writing twenty hooks to show a list would stall the screen.

## 2. Judged art
`fill_art` and the quad style's `_fill_scenes` both take "the first picture that passes".
With a judge they take the best of up to `JUDGED` (6) that pass:
- A candidate still has to pass today's checks first (not seen, not another title's picture,
  no words on it).
- Each is judged against the title's AniList cover as a reference. `ok=False` drops it; the
  highest score wins; a tie keeps the source's order.
- Every verdict `None` → the first passing candidate, as today. Every candidate rejected →
  the title keeps its own art, and the progress line says why.
- Verdicts are cached as `judge:<anilist_id>:<sha256>:<model>`.

Without a judge nothing changes. The manual pickers (`--list`/`--pick`, the TUI art screen,
the web picker) are untouched.

## 3. `manhwatok auto`

### Account
`auto_upload: bool = False`, set with `account set --auto-upload / --no-auto-upload`.

### `app/auto.py`
`tick(ctx, now, days, upload, log) -> TickReport`, with no sleeping in it:
1. Every account with slots and a rotation is filled (`fill_plan.fill`). One account's failure
   is logged and the others still run.
2. For each `auto_upload` account, the oldest unsent post that came due in the last `LATE`
   (6 h) is uploaded, at most one per tick. The upload is never told "yes" by a person, so a
   post counts as sent only when the phone reports it tapped Post itself.
3. A post that did not go out has its `auto_tries` raised; at `MAX_TRIES` (2) it is left
   overdue for the Queue tab.

Uploading needs `MANHWATOK_UPLOADER=phone`; `auto` builds that uploader with auto-post on.
With the browser uploader `auto` only builds and queues, and says so once.

### CLI
`manhwatok auto [--days 7] [--every 15] [--once]` loops `tick`, sleeping `--every` minutes;
`--once` runs a single tick (for cron or launchd). A pid lock at `data_dir/auto.lock` refuses a
second copy.

## Out of scope
- Unattended browser uploads and TikTok-side scheduling.
- A generated caption or chapter recap.
- Judging slide fit (the CLIP crop picker already does that at render time).
