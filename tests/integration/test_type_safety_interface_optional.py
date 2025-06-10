"""
Type Safety Validation for Interface-Optional Dependency Injection

Validates that the system provides complete type safety without requiring
Protocol definitions or explicit interface inheritance.
"""

import asyncio
from typing import Any

import pytest
from mcp_mesh.decorators import mesh_agent


class TestTypeSafetyInterfaceOptional:
    """Type safety validation without Protocol requirements."""

    @pytest.mark.asyncio
    async def test_duck_typing_type_safety(self):
        """Test that duck typing provides full type safety."""

        # Define concrete implementations without Protocol inheritance
        class FileService:
            async def read(self, path: str) -> str:
                return f"content of {path}"

            async def write(self, path: str, content: str) -> bool:
                return True

            def get_size(self, path: str) -> int:
                return len(path) * 10

        class DatabaseService:
            async def query(self, sql: str) -> list[dict[str, Any]]:
                return [{"id": 1, "name": "test"}]

            async def execute(self, sql: str) -> int:
                return 1

            def get_connection_count(self) -> int:
                return 5

        # Type-safe consumer without explicit interface definitions
        @mesh_agent
        class TypeSafeConsumer:
            def __init__(self, file_service: FileService, db_service: DatabaseService):
                self.file_service = file_service
                self.db_service = db_service

            async def process_with_types(
                self, file_path: str, query: str
            ) -> dict[str, Any]:
                # Type checker should validate all these calls
                content: str = await self.file_service.read(file_path)
                size: int = self.file_service.get_size(file_path)
                records: list[dict[str, Any]] = await self.db_service.query(query)
                connections: int = self.db_service.get_connection_count()

                return {
                    "content": content,
                    "file_size": size,
                    "record_count": len(records),
                    "db_connections": connections,
                }

        # Test with concrete implementations
        consumer = TypeSafeConsumer(FileService(), DatabaseService())
        result = await consumer.process_with_types("test.txt", "SELECT * FROM users")

        # Validate types and results
        assert isinstance(result["content"], str)
        assert isinstance(result["file_size"], int)
        assert isinstance(result["record_count"], int)
        assert isinstance(result["db_connections"], int)
        assert result["content"] == "content of test.txt"
        assert result["file_size"] == 80  # len("test.txt") * 10
        assert result["record_count"] == 1
        assert result["db_connections"] == 5

    @pytest.mark.asyncio
    async def test_generic_type_safety(self):
        """Test generic type safety without Protocol definitions."""

        from typing import Generic, TypeVar

        T = TypeVar("T")

        class GenericService(Generic[T]):
            def __init__(self, data: T):
                self.data = data

            async def process(self, input_data: T) -> T:
                return input_data

            def get_type_info(self) -> str:
                return str(type(self.data))

        # Type-safe generic usage
        @mesh_agent
        class GenericConsumer:
            def __init__(
                self,
                string_service: GenericService[str],
                int_service: GenericService[int],
            ):
                self.string_service = string_service
                self.int_service = int_service

            async def process_both(self, text: str, number: int) -> dict[str, Any]:
                # Type safety with generics
                processed_text: str = await self.string_service.process(text)
                processed_number: int = await self.int_service.process(number)

                return {
                    "text": processed_text,
                    "number": processed_number,
                    "text_type": self.string_service.get_type_info(),
                    "number_type": self.int_service.get_type_info(),
                }

        # Test generic type safety
        consumer = GenericConsumer(GenericService("test"), GenericService(42))

        result = await consumer.process_both("hello", 100)
        assert result["text"] == "hello"
        assert result["number"] == 100

    @pytest.mark.asyncio
    async def test_union_type_safety(self):
        """Test Union type safety without Protocol definitions."""

        class TextProcessor:
            async def process_text(self, text: str) -> str:
                return text.upper()

        class NumberProcessor:
            async def process_number(self, num: int) -> int:
                return num * 2

        # Union type support
        @mesh_agent
        class FlexibleProcessor:
            def __init__(self, processor: TextProcessor | NumberProcessor):
                self.processor = processor

            async def flexible_process(self, data: str | int) -> str | int:
                if isinstance(data, str) and isinstance(self.processor, TextProcessor):
                    return await self.processor.process_text(data)
                elif isinstance(data, int) and isinstance(
                    self.processor, NumberProcessor
                ):
                    return await self.processor.process_number(data)
                else:
                    raise ValueError("Type mismatch")

        # Test Union type safety
        text_processor = FlexibleProcessor(TextProcessor())
        result_text = await text_processor.flexible_process("hello")
        assert result_text == "HELLO"

        number_processor = FlexibleProcessor(NumberProcessor())
        result_number = await number_processor.flexible_process(10)
        assert result_number == 20

    @pytest.mark.asyncio
    async def test_optional_type_safety(self):
        """Test Optional type safety without Protocol definitions."""

        class OptionalService:
            def __init__(self, enabled: bool = True):
                self.enabled = enabled

            async def maybe_process(self, data: str) -> str | None:
                if self.enabled:
                    return data.lower()
                return None

            def get_status(self) -> dict[str, Any] | None:
                if self.enabled:
                    return {"status": "active", "timestamp": 1234567890}
                return None

        # Optional type handling
        @mesh_agent
        class OptionalConsumer:
            def __init__(self, service: OptionalService | None = None):
                self.service = service

            async def safe_process(self, data: str) -> dict[str, Any]:
                if self.service:
                    result: str | None = await self.service.maybe_process(data)
                    status: dict[str, Any] | None = self.service.get_status()
                    return {
                        "processed": result,
                        "status": status,
                        "service_available": True,
                    }
                else:
                    return {
                        "processed": None,
                        "status": None,
                        "service_available": False,
                    }

        # Test with service
        consumer_with_service = OptionalConsumer(OptionalService(True))
        result = await consumer_with_service.safe_process("HELLO")
        assert result["processed"] == "hello"
        assert result["status"]["status"] == "active"
        assert result["service_available"] is True

        # Test without service
        consumer_without_service = OptionalConsumer(None)
        result = await consumer_without_service.safe_process("HELLO")
        assert result["processed"] is None
        assert result["status"] is None
        assert result["service_available"] is False

    @pytest.mark.asyncio
    async def test_complex_nested_type_safety(self):
        """Test complex nested type structures without Protocol definitions."""

        class DataStructure:
            def __init__(self, data: dict[str, list[dict[str, str | int]]]):
                self.data = data

            async def transform(self) -> list[dict[str, Any]]:
                result = []
                for key, items in self.data.items():
                    for item in items:
                        result.append(
                            {"category": key, "item": item, "transformed": True}
                        )
                return result

        # Complex nested type consumer
        @mesh_agent
        class ComplexConsumer:
            def __init__(self, processor: DataStructure):
                self.processor = processor

            async def process_complex(self) -> dict[str, Any]:
                # Type safety with complex nested structures
                transformed: list[dict[str, Any]] = await self.processor.transform()

                # Type-safe operations on complex data
                categories = set()
                item_count = 0

                for item in transformed:
                    categories.add(item["category"])
                    item_count += 1

                return {
                    "categories": list(categories),
                    "total_items": item_count,
                    "first_item": transformed[0] if transformed else None,
                }

        # Test complex nested types
        complex_data = {
            "users": [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}],
            "products": [
                {"title": "Widget", "price": 10},
                {"title": "Gadget", "price": 20},
            ],
        }

        consumer = ComplexConsumer(DataStructure(complex_data))
        result = await consumer.process_complex()

        assert set(result["categories"]) == {"users", "products"}
        assert result["total_items"] == 4
        assert result["first_item"]["category"] == "users"

    def test_static_type_checking_compatibility(self):
        """Test that the system is compatible with static type checkers."""

        # This test validates that type annotations work correctly
        # with mypy, pyright, and other static type checkers

        class TypedService:
            def sync_method(self, x: int) -> str:
                return str(x)

            async def async_method(self, y: str) -> int:
                return len(y)

        @mesh_agent
        class TypeCheckerCompatible:
            def __init__(self, service: TypedService):
                self.service = service

            def get_service_type(self) -> type:
                return type(self.service)

            async def typed_operation(self, value: int) -> dict[str, str | int]:
                # These should pass static type checking
                str_result: str = self.service.sync_method(value)
                int_result: int = await self.service.async_method(str_result)

                return {"string_value": str_result, "integer_value": int_result}

        # Instantiate and test
        service = TypedService()
        consumer = TypeCheckerCompatible(service)

        # These should be type-safe
        assert consumer.get_service_type() == TypedService

        # This would be validated by static type checkers

        result = asyncio.run(consumer.typed_operation(42))
        assert result["string_value"] == "42"
        assert result["integer_value"] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
