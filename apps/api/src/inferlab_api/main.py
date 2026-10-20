"""Health-only development entry point. No inference or mutation endpoints."""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

app = FastAPI(title="InferLab local API", version="0.1.0", docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])


class HealthResponse(BaseModel):
    """Process liveness only; this does not report GPU readiness."""

    status: Literal["ok"] = "ok"
    execution: Literal["not_configured"] = "not_configured"


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()
