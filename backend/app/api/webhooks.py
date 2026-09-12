"""Provider webhooks.

Some video providers finish a job minutes later and call us back instead of
being polled. Three rules govern that door:

1. **Authenticate.** A callback is an unauthenticated HTTP request from the
   internet. Without a verified signature it is a stranger claiming a render
   finished, so an unsigned callback is rejected, not trusted.
2. **Be idempotent.** Providers retry. The same delivery must never create a
   second cost row or a second file.
3. **Never take the payload's word for the money.** A webhook says a job is
   done; what it cost is read from our own ledger and the provider's usage
   fields, never from an attacker-controllable number.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import settings
from app.core.db import utcnow
from app.core.enums import JobStatus
from app.models import GenerationJob
from fastapi import Depends

log = logging.getLogger("adflow.webhooks")

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

#: Providers we are prepared to receive callbacks from. Adding one here is
#: deliberate — an unknown provider path 404s rather than being accepted.
KNOWN_PROVIDERS = {"veo", "runway", "seedance", "music", "elevenlabs"}


def _secret_for(provider: str) -> Optional[str]:
    """The shared secret for this provider's callbacks.

    Falls back to the global WEBHOOK_SECRET so a single-provider deployment
    needs one variable, not five.
    """
    specific = getattr(settings, f"{provider.upper()}_WEBHOOK_SECRET", None)
    return specific or getattr(settings, "WEBHOOK_SECRET", None)


def verify_signature(provider: str, body: bytes, signature: Optional[str]) -> bool:
    """HMAC-SHA256 over the raw body, compared in constant time.

    Returns False when no secret is configured: an endpoint that cannot verify
    must not accept. That is a deliberate fail-closed choice — a webhook that
    silently trusts everything is worse than one that is switched off.
    """
    secret = _secret_for(provider)
    if not secret or not signature:
        return False
    provided = signature.strip()
    for prefix in ("sha256=", "hmac-sha256=", "v1="):
        if provided.lower().startswith(prefix):
            provided = provided[len(prefix):]
            break
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided)


def _already_handled(job: GenerationJob, delivery_id: str) -> bool:
    handled = (job.result or {}).get("_webhook_deliveries") or []
    return delivery_id in handled


def _record_delivery(job: GenerationJob, delivery_id: str) -> None:
    result = dict(job.result or {})
    deliveries = list(result.get("_webhook_deliveries") or [])
    deliveries.append(delivery_id)
    result["_webhook_deliveries"] = deliveries[-20:]
    job.result = result


@router.post("/{provider}", status_code=status.HTTP_202_ACCEPTED)
def provider_callback(
    provider: str,
    request: Request,
    response: Response,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    x_signature: Optional[str] = Header(default=None, alias="X-Signature"),
    x_delivery_id: Optional[str] = Header(default=None, alias="X-Delivery-Id"),
) -> Dict[str, Any]:
    """Accept a provider's completion callback for one generation job."""
    provider = provider.lower()
    if provider not in KNOWN_PROVIDERS:
        response.status_code = status.HTTP_404_NOT_FOUND
        return {"ok": False, "error": "unknown provider"}

    raw = getattr(request.state, "raw_body", None)
    if raw is None:
        # Body already consumed by FastAPI; rebuild a stable representation.
        import json as _json

        raw = _json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()

    if not verify_signature(provider, raw, x_signature):
        log.warning("rejected unsigned webhook", extra={"provider": provider})
        response.status_code = status.HTTP_401_UNAUTHORIZED
        return {"ok": False, "error": "signature verification failed"}

    job_id = str(payload.get("job_id") or payload.get("metadata", {}).get("job_id") or "")
    job = db.get(GenerationJob, job_id) if job_id else None
    if job is None:
        log.warning("webhook for unknown job", extra={"provider": provider, "job_id": job_id})
        response.status_code = status.HTTP_404_NOT_FOUND
        return {"ok": False, "error": "unknown job"}

    delivery_id = x_delivery_id or hashlib.sha256(raw).hexdigest()[:32]
    if _already_handled(job, delivery_id):
        # Retries are normal and must be free of side effects.
        return {"ok": True, "duplicate": True, "job_id": job.id, "status": job.status}

    state = str(payload.get("status") or payload.get("state") or "").lower()
    result = dict(job.result or {})
    result.update({
        "provider_status": state,
        "provider_job_id": payload.get("id") or payload.get("task_id"),
        "callback_received_at": utcnow().isoformat(),
    })
    output_url = payload.get("output_url") or payload.get("url") or (
        (payload.get("output") or {}).get("url") if isinstance(payload.get("output"), dict) else None
    )
    if output_url:
        result["provider_output_url"] = output_url

    if state in {"succeeded", "completed", "done", "success"}:
        job.progress = max(job.progress, 0.9)
        job.progress_label = "provider finished — collecting output"
    elif state in {"failed", "error", "cancelled", "canceled"}:
        job.status = JobStatus.FAILED.value if state != "cancelled" else JobStatus.CANCELLED.value
        job.error_message = str(payload.get("error") or payload.get("message") or state)[:500]
        job.finished_at = utcnow()

    job.result = result
    _record_delivery(job, delivery_id)
    db.commit()
    log.info("webhook accepted", extra={"provider": provider, "job_id": job.id,
                                        "provider_status": state})
    return {"ok": True, "job_id": job.id, "status": job.status}


@router.get("/{provider}/health")
def webhook_health(provider: str) -> Dict[str, Any]:
    """Tells an operator whether this callback path can actually be used."""
    provider = provider.lower()
    return {
        "provider": provider,
        "known": provider in KNOWN_PROVIDERS,
        # Only whether a secret exists — never the secret.
        "signature_verification_configured": bool(_secret_for(provider)),
        "path": f"{settings.API_PREFIX}/webhooks/{provider}",
    }
