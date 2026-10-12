from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import models  # noqa: F401 - registra os modelos no metadata.
from app.api.routes.jobs import router as jobs_router
from app.api.routes.notifications import router as notifications_router
from app.api.routes.profile import router as profile_router
from app.db.base import Base
from app.db.migrations import upgrade_schema
from app.db.session import engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    upgrade_schema(engine)
    yield


app = FastAPI(title="Job Hunter API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type"],
)
app.include_router(profile_router, prefix="/api")
app.include_router(jobs_router, prefix="/api")
app.include_router(notifications_router, prefix="/api")


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
