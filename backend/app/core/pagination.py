from __future__ import annotations
from pydantic import BaseModel
from typing import Generic, List, TypeVar, Optional

T = TypeVar("T")

class Page(BaseModel, Generic[T]):
    items: List[T]
    total: int
    limit: int
    offset: int
