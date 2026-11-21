
from fastapi import FastAPI

app = FastAPI(
    title="Peligrosa API",
    description="Peligrosa AI Companion Platform",
    version="0.1.0"
)


@app.get("/")
async def root():
    return {
        "project": "Peligrosa",
        "status": "running",
        "message": "Welcome to Peligrosa!"
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
