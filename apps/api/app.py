from fastapi import FastAPI

from apps.api.routers.dashboard import router as dashboard_router


def create_app() -> FastAPI:
    """Create the read-only dashboard API application.

    @returns: Configured FastAPI application.
    """
    application = FastAPI(
        title="Trading Bot Dashboard API",
        version="0.9.0",
    )
    application.include_router(dashboard_router)
    return application


app = create_app()
