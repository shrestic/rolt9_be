from typing import TypeVar

from pydantic import BaseModel

# Generic type for your data
T = TypeVar("T")


class CustomResponse[T](BaseModel):
    success: bool = True
    data: T | None = None
    message: str | None = None
    errors: list[str] | None = None
    error_code: str | None = None
