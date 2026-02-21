from collections.abc import Callable


class HotReloadStore:
    def __init__(
        self,
        schema: dict[str, object],
        initial: dict[str, object] | None = ...,
    ) -> None: ...
    def get(self, key: str) -> object: ...
    def set(self, key: str, value: object) -> None: ...
    def update(self, values: dict[str, object]) -> None: ...
    def reconcile(
        self,
        schema: dict[str, object],
        setup_fn: Callable[[HotReloadStore], list[object] | None],
    ) -> None: ...
