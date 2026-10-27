from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import models as _models  # noqa: F401
from app.api.router import api_router, public_router
from app.bootstrap import register_providers
from app.common.config import settings
from app.common.exceptions import DomainError
from app.modules.referrals import services as _referrals  # noqa: F401


def create_app() -> FastAPI:
    register_providers()
    app = FastAPI(title="TargetologAI API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            *settings.csrf_trusted_origins,
            *settings.cors_allowed_origins,
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message, "code": exc.code}
            | (
                {"problems": problems}
                if (problems := getattr(exc, "problems", None))
                else {}
            ),
        )

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(api_router)
    app.include_router(public_router)
    return app


app = create_app()
