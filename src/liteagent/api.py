import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .engine import Engine
from .jobs import JobStore, Worker


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


def create_app(
    engine: Engine,
    store: JobStore,
    worker: Worker | None = None,
    on_startup: Callable[[], Awaitable[object]] | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = None
        startup_task = None
        if worker is not None:
            store.requeue_running()
            task = asyncio.create_task(worker.run_forever())
        if on_startup is not None:
            startup_task = asyncio.create_task(on_startup())  # background: never delays serving
        try:
            yield
        finally:
            for t in (task, startup_task):
                if t is not None:
                    t.cancel()
                    with suppress(asyncio.CancelledError):
                        await t

    app = FastAPI(lifespan=lifespan)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/message")
    async def post_message(body: MessageIn):
        reply = await engine.handle(body.text)
        return {
            "kind": reply.kind,
            "route": reply.route.value,
            "text": reply.text,
            "job_id": reply.job_id,
        }

    @app.get("/jobs/{job_id}")
    async def get_job(job_id: str):
        job = store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return {
            "id": job.id,
            "route": job.route,
            "status": job.status,
            "result": job.result,
            "error": job.error,
        }

    return app
