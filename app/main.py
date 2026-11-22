from fastapi import FastAPI
from app.core.config import settings
from app.core.logging_config import setup_logging

setup_logging()

app = FastAPI(
    title=f"{settings.APP_NAME} API",
    description="Peligrosa AI Companion Platform",
    version="0.1.0",
)


@app.get("/")
async def root():
    return {
        "project": settings.APP_NAME,
        "environment": settings.APP_ENV,
        "status": "running",
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
