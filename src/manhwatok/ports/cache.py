from typing import Protocol


class Cache(Protocol):
    def get(self, key: str, max_age: float) -> str | None: ...

    def put(self, key: str, value: str) -> None: ...
