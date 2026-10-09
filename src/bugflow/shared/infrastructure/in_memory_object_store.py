"""An object store that keeps its objects in a dictionary, for tests. Writing
a key twice is an error, since a real key is never overwritten.
"""


class InMemoryObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.content_types: dict[str, str] = {}

    def put(
        self,
        key: str,
        body: bytes,
        content_type: str = "application/json",
        content_encoding: str | None = "gzip",
    ) -> None:
        if key in self.objects:
            raise AssertionError(f"{key} written twice; keys are write-once")
        self.objects[key] = body
        self.content_types[key] = content_type

    def get(self, key: str) -> bytes | None:
        return self.objects.get(key)

    def has(self, key: str) -> bool:
        return key in self.objects

    @property
    def configured(self) -> bool:
        return True
