from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginatedResponse[T](BaseModel):
    """
    Generic paginated response schema.

    This schema is used for API responses that return paginated lists of items.
    """

    items: list[T]
    total: int
    page: int
    size: int
    pages: int
