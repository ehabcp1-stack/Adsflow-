"""Friendly, typed API errors. Never leak stack traces to normal users."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse


class AdFlowError(HTTPException):
    code = "adflow_error"
    http_status = status.HTTP_400_BAD_REQUEST

    def __init__(self, message: str, message_ar: Optional[str] = None, **extra: Any):
        self.message = message
        self.message_ar = message_ar or message
        self.extra: Dict[str, Any] = extra
        super().__init__(status_code=self.http_status, detail=message)

    def to_payload(self) -> Dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "message_ar": self.message_ar,
                **self.extra,
            }
        }


class NotFound(AdFlowError):
    code = "not_found"
    http_status = status.HTTP_404_NOT_FOUND


class InvalidStateTransition(AdFlowError):
    code = "invalid_state_transition"
    http_status = status.HTTP_409_CONFLICT


class ApprovalMissing(AdFlowError):
    code = "approval_required"
    http_status = status.HTTP_409_CONFLICT


class BudgetExceeded(AdFlowError):
    code = "budget_exceeded"
    http_status = status.HTTP_402_PAYMENT_REQUIRED


class SceneLocked(AdFlowError):
    code = "scene_locked"
    http_status = status.HTTP_409_CONFLICT


class ProviderUnavailable(AdFlowError):
    code = "provider_unavailable"
    http_status = status.HTTP_503_SERVICE_UNAVAILABLE


class QCFailed(AdFlowError):
    code = "qc_failed"
    http_status = status.HTTP_409_CONFLICT


async def adflow_error_handler(_: Request, exc: AdFlowError) -> JSONResponse:
    return JSONResponse(status_code=exc.http_status, content=exc.to_payload())


async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:  # pragma: no cover
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "Something went wrong on our side. Please try again.",
                "message_ar": "صار خطأ من طرفنا. جرّب مرة ثانية.",
            }
        },
    )
