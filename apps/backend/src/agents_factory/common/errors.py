from typing import TypedDict


class ProblemDetails(TypedDict):
    type: str
    title: str
    status: int
    detail: str
    code: str
    correlation_id: str


class DomainError(Exception):
    """A safe, stable error that may cross the HTTP boundary."""

    def __init__(
        self,
        *,
        type: str,
        title: str,
        status: int,
        detail: str,
        code: str,
    ) -> None:
        super().__init__(detail)
        self.type = type
        self.title = title
        self.status = status
        self.detail = detail
        self.code = code

    def to_problem_details(self, *, correlation_id: str) -> ProblemDetails:
        return {
            "type": self.type,
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
            "code": self.code,
            "correlation_id": correlation_id,
        }
