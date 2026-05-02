#!/usr/bin/env python3
"""Schema-corpus producer (Python) — 12-pattern matrix for issue #547 Phase 7.

One agent declaring twelve tools, each producing a different schema pattern from
the cross-runtime canonical-form spike. Paired with TypeScript and Java corpus
producers to prove end-to-end that all twelve patterns canonicalize to the same
hash across runtimes.

Pattern source: ``~/workspace/schema-spike-547/python/extract.py``.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import List, Literal, Optional, Union

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel, Field
from typing_extensions import Annotated


# ===== Pattern 1: Primitives =====
class Primitives(BaseModel):
    id: str
    age: int
    active: bool
    score: float


# ===== Pattern 2: Optional =====
class WithOptional(BaseModel):
    name: str
    nickname: Optional[str] = None


# ===== Pattern 3: WithDate =====
class WithDate(BaseModel):
    hireDate: date


# ===== Pattern 4: WithEnum =====
class RoleEnum(str, Enum):
    admin = "admin"
    user = "user"
    guest = "guest"


class WithEnum(BaseModel):
    role: RoleEnum


# ===== Pattern 5: Nested =====
class Employee(BaseModel):
    name: str
    dept: str


class Nested(BaseModel):
    employee: Employee


# ===== Pattern 6: WithArray =====
class WithArray(BaseModel):
    tags: List[str]


# ===== Pattern 7: CaseConversion (snake_case input -> camelCase canonical) =====
class CaseConversion(BaseModel):
    market_cap: float
    hire_date: date
    is_active: bool


# ===== Pattern 8: DiscriminatedUnion =====
class Dog(BaseModel):
    kind: Literal["dog"]
    breed: str


class Cat(BaseModel):
    kind: Literal["cat"]
    indoor: bool


class WithAnimal(BaseModel):
    pet: Annotated[Union[Dog, Cat], Field(discriminator="kind")]


# ===== Pattern 9: Recursive =====
class TreeNode(BaseModel):
    value: str
    children: List["TreeNode"]


TreeNode.model_rebuild()


# ===== Pattern 10: Inheritance =====
class EmployeeBase(BaseModel):
    name: str
    dept: str


class Manager(EmployeeBase):
    reports: int


class WithManager(BaseModel):
    person: Manager


# ===== Pattern 11: NumberConstraints =====
class WithScore(BaseModel):
    value: int = Field(ge=0, le=100)


# ===== Pattern 12: UntaggedUnion =====
class WithEither(BaseModel):
    value: Union[str, int]


# ===== Agent + tools =====

app = FastMCP("Schema Corpus (Python)")


@app.tool()
@mesh.tool(
    capability="corpus_primitives",
    description="Pattern 1: Primitives (str, int, bool, float)",
)
def get_primitives() -> Primitives:
    return Primitives(id="A1", age=42, active=True, score=3.14)


@app.tool()
@mesh.tool(
    capability="corpus_optional",
    description="Pattern 2: Optional[str] field",
)
def get_optional() -> WithOptional:
    return WithOptional(name="Alice", nickname=None)


@app.tool()
@mesh.tool(
    capability="corpus_with_date",
    description="Pattern 3: date field (Pydantic emits format=date)",
)
def get_with_date() -> WithDate:
    return WithDate(hireDate=date(2024, 1, 15))


@app.tool()
@mesh.tool(
    capability="corpus_with_enum",
    description="Pattern 4: enum with values [admin, user, guest]",
)
def get_with_enum() -> WithEnum:
    return WithEnum(role=RoleEnum.admin)


@app.tool()
@mesh.tool(
    capability="corpus_nested",
    description="Pattern 5: Nested model (Employee inside Nested)",
)
def get_nested() -> Nested:
    return Nested(employee=Employee(name="Alice", dept="Engineering"))


@app.tool()
@mesh.tool(
    capability="corpus_with_array",
    description="Pattern 6: list[str]",
)
def get_with_array() -> WithArray:
    return WithArray(tags=["alpha", "beta"])


@app.tool()
@mesh.tool(
    capability="corpus_case_conversion",
    description="Pattern 7: snake_case input (normalizer converts to camelCase)",
)
def get_case_conversion() -> CaseConversion:
    return CaseConversion(market_cap=1.0e9, hire_date=date(2024, 1, 15), is_active=True)


@app.tool()
@mesh.tool(
    capability="corpus_discriminated_union",
    description="Pattern 8: DiscriminatedUnion (Dog|Cat by 'kind')",
)
def get_discriminated_union() -> WithAnimal:
    return WithAnimal(pet=Dog(kind="dog", breed="Lab"))


@app.tool()
@mesh.tool(
    capability="corpus_recursive",
    description="Pattern 9: Recursive TreeNode (self-reference)",
)
def get_recursive() -> TreeNode:
    return TreeNode(value="root", children=[TreeNode(value="child", children=[])])


@app.tool()
@mesh.tool(
    capability="corpus_inheritance",
    description="Pattern 10: Inheritance (Manager extends EmployeeBase, flattened)",
)
def get_inheritance() -> WithManager:
    return WithManager(person=Manager(name="Alice", dept="Engineering", reports=5))


@app.tool()
@mesh.tool(
    capability="corpus_number_constraints",
    description="Pattern 11: NumberConstraints (Field ge=0 le=100)",
)
def get_number_constraints() -> WithScore:
    return WithScore(value=50)


@app.tool()
@mesh.tool(
    capability="corpus_untagged_union",
    description="Pattern 12: UntaggedUnion (str|int, no discriminator)",
)
def get_untagged_union() -> WithEither:
    return WithEither(value="forty-two")


@mesh.agent(
    name="corpus-py",
    version="1.0.0",
    description="Schema-corpus producer (Python) — 12 patterns for issue #547 Phase 7",
    http_port=9200,
    enable_http=True,
    auto_run=True,
)
class CorpusAgent:
    pass
