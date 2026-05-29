from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.dtos.custom_response_dto import CustomResponse


def create_response[T](
    data: T | None = None,  # type: ignore
    message: str | None = None,
    errors: list[str] | None = None,
    error_code: str | None = None,
    success: bool = True,
    status_code: int = 200,
):
    response = CustomResponse[T](
        success=success, data=data, message=message, errors=errors, error_code=error_code
    )
    return JSONResponse(status_code=status_code, content=jsonable_encoder(response))
