"""Fast JSON operations using orjson with stdlib fallback."""

try:
    import orjson

    def dumps(obj) -> str:
        """Serialize to JSON string. Uses orjson for speed."""
        return orjson.dumps(obj).decode("utf-8")

    def dumps_bytes(obj) -> bytes:
        """Serialize to JSON bytes. Uses orjson for speed."""
        return orjson.dumps(obj)

    def loads(data):
        """Deserialize JSON string or bytes. Uses orjson for speed."""
        return orjson.loads(data)

except ImportError:
    import json

    def dumps(obj) -> str:
        return json.dumps(obj)

    def dumps_bytes(obj) -> bytes:
        return json.dumps(obj).encode("utf-8")

    def loads(data):
        return json.loads(data)
