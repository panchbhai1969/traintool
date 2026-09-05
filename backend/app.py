from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Literal

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, Field, field_validator

from .dataset import DatasetCatalog
from .evaluator import evaluate_one
from .settings import DEFAULT_MODEL, OPENROUTER_API_KEY_KEY, ROOT


catalog = DatasetCatalog()
app = FastAPI(title="Dental Stain Prompt Lab")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


DEFAULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["stain_present", "confidence", "stain_type", "surface", "severity", "reasoning", "differential_considered"],
    "properties": {
        "stain_present": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "stain_type": {"enum": ["chromogenic", "tobacco", "chlorhexidine", "food_beverage", "uncertain", "none"]},
        "surface": {"enum": ["cervical", "occlusal_pits", "interproximal", "full_facial", "other"]},
        "severity": {"enum": ["none", "mild", "moderate", "heavy"]},
        "reasoning": {"type": "string"},
        "differential_considered": {"type": "array", "items": {"type": "string"}},
    },
}


class EvaluationRequest(BaseModel):
    crop_ids: list[str] = Field(min_length=1, max_length=250)
    prompt: str = Field(min_length=1, max_length=50_000)
    schema_: dict[str, Any] = Field(alias="schema")
    model: str = Field(default=DEFAULT_MODEL, min_length=1, max_length=300)
    temperature: float = Field(default=0, ge=0, le=2)
    max_tokens: int = Field(default=800, ge=1, le=16_384)
    max_edge: int = Field(default=896, ge=128, le=4096)
    padding: float = Field(default=0.25, ge=0, le=1)
    mode: Literal["sequential", "parallel"] = "parallel"
    concurrency: int = Field(default=8, ge=1, le=32)

    @field_validator("schema_")
    @classmethod
    def valid_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            Draft202012Validator.check_schema(value)
        except SchemaError as error:
            raise ValueError(f"Invalid JSON Schema: {error.message}") from error
        return value


@app.get("/dataset.json", include_in_schema=False)
async def dataset() -> JSONResponse:
    return JSONResponse({**catalog.payload(), "defaults": {"model": DEFAULT_MODEL, "schema": DEFAULT_SCHEMA}})


@app.post("/api/evaluate")
async def evaluate(payload: EvaluationRequest, request: Request) -> StreamingResponse:
    api_key = os.getenv(OPENROUTER_API_KEY_KEY)
    if not api_key:
        raise HTTPException(status_code=503, detail="OPENROUTER_API_KEY is not configured")
    unknown = [crop_id for crop_id in payload.crop_ids if crop_id not in catalog.crops]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown crop ID: {unknown[0]}")

    async def stream():
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        limit = 1 if payload.mode == "sequential" else payload.concurrency
        semaphore = asyncio.Semaphore(limit)

        async def emit(event: dict[str, Any]) -> None:
            await queue.put(event)

        async def run(crop_id: str, client: httpx.AsyncClient) -> None:
            await emit({"type": "queued", "crop_id": crop_id})
            async with semaphore:
                await evaluate_one(
                    client,
                    catalog.crops[crop_id],
                    api_key=api_key,
                    model=payload.model,
                    prompt=payload.prompt,
                    schema=payload.schema_,
                    temperature=payload.temperature,
                    max_tokens=payload.max_tokens,
                    max_edge=payload.max_edge,
                    padding=payload.padding,
                    emit=emit,
                )

        async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=15)) as client:
            tasks = [asyncio.create_task(run(crop_id, client)) for crop_id in dict.fromkeys(payload.crop_ids)]
            remaining = len(tasks)
            try:
                while remaining:
                    if await request.is_disconnected():
                        break
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=0.5)
                    except TimeoutError:
                        remaining = sum(not task.done() for task in tasks)
                        continue
                    yield f"data: {json.dumps(event, separators=(',', ':'))}\n\n"
                    remaining = sum(not task.done() for task in tasks)
                while not queue.empty():
                    event = queue.get_nowait()
                    yield f"data: {json.dumps(event, separators=(',', ':'))}\n\n"
                if all(task.done() for task in tasks):
                    yield 'data: {"type":"batch_completed"}\n\n'
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


FRONTEND = ROOT / "frontend"


@app.get("/{path:path}", include_in_schema=False)
async def frontend(path: str):
    candidate = (FRONTEND / path).resolve()
    if path and candidate.is_file() and FRONTEND in candidate.parents:
        return FileResponse(candidate)
    return FileResponse(FRONTEND / "index.html")
