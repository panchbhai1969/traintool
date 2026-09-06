from __future__ import annotations

import asyncio
import io
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field, field_validator

from .dataset import DatasetCatalog
from .evaluator import evaluate_one
from .prompts import DEFAULT_FINDING, FINDINGS, load_prompts, save_prompt
from .settings import DEFAULT_MODEL, OPENROUTER_API_KEY_KEY, ROOT, UPLOAD_DIR
from .tooth_extractor import ToothExtractionError, extract_teeth


catalog = DatasetCatalog()
uploaded_sources: dict[str, tuple[Path, str]] = {}
app = FastAPI(title="Dental Finding Prompt Lab")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["*"],
)


DEFAULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reasoning", "verdict"],
    "properties": {
        "reasoning": {
            "type": "string",
            "description": "A detailed, coherent visual explanation supporting the verdict.",
        },
        "verdict": {"type": "string", "enum": ["present", "absent"]},
    },
}

MAX_UPLOAD_BYTES = 30 * 1024 * 1024
SUPPORTED_IMAGE_FORMATS = {
    "JPEG": (".jpg", "image/jpeg"),
    "PNG": (".png", "image/png"),
    "WEBP": (".webp", "image/webp"),
}


class EvaluationRequest(BaseModel):
    crop_ids: list[str] = Field(min_length=1, max_length=250)
    prompt: str = Field(min_length=1, max_length=50_000)
    schema_: dict[str, Any] = Field(alias="schema")
    model: str = Field(default=DEFAULT_MODEL, min_length=1, max_length=300)
    max_tokens: int = Field(default=800, ge=1, le=16_384)
    max_edge: int = Field(default=896, ge=128, le=4096)
    padding: float = Field(default=0.25, ge=0, le=1)
    finding: Literal["stain", "calculus", "caries"] = DEFAULT_FINDING
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


class PromptUpdate(BaseModel):
    prompt: str = Field(min_length=1, max_length=50_000)


@app.get("/dataset.json", include_in_schema=False)
async def dataset() -> JSONResponse:
    return JSONResponse(
        {
            **catalog.payload(),
            "defaults": {
                "model": DEFAULT_MODEL,
                "schema": DEFAULT_SCHEMA,
                "finding": DEFAULT_FINDING,
                "prompts": load_prompts(),
            },
        }
    )


@app.put("/api/prompts/{finding}")
async def update_prompt(finding: str, payload: PromptUpdate) -> JSONResponse:
    if finding not in FINDINGS:
        raise HTTPException(status_code=404, detail="Unknown finding")
    try:
        prompt = await asyncio.to_thread(save_prompt, finding, payload.prompt)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return JSONResponse({"finding": finding, "prompt": prompt})


def _inspect_upload(contents: bytes) -> tuple[int, int, str, str]:
    try:
        with Image.open(io.BytesIO(contents)) as image:
            image.verify()
        with Image.open(io.BytesIO(contents)) as image:
            width, height = image.size
            image_format = str(image.format or "").upper()
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError("Upload is not a valid image") from error
    if image_format not in SUPPORTED_IMAGE_FORMATS:
        raise ValueError("Only JPEG, PNG, and WebP images are supported")
    if width <= 0 or height <= 0:
        raise ValueError("Image dimensions are invalid")
    extension, media_type = SUPPORTED_IMAGE_FORMATS[image_format]
    return width, height, extension, media_type


def _upload_image_id(filename: str | None) -> str:
    stem = Path(filename or "image").stem.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")[:32] or "image"
    return f"upload-{slug}-{uuid.uuid4().hex[:8]}"


@app.post("/api/images/upload")
async def upload_image(request: Request) -> JSONResponse:
    chunks: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Uploaded image exceeds the 30 MB limit")
        chunks.append(chunk)
    contents = b"".join(chunks)
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded image is empty")
    try:
        width, height, extension, media_type = await asyncio.to_thread(_inspect_upload, contents)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    try:
        detections = await extract_teeth(contents)
    except ToothExtractionError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    encoded_filename = request.headers.get("x-filename")
    image_id = _upload_image_id(unquote(encoded_filename) if encoded_filename else None)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    source_path = UPLOAD_DIR / f"{image_id}{extension}"
    temporary_path = source_path.with_suffix(f"{extension}.tmp")
    temporary_path.write_bytes(contents)
    temporary_path.replace(source_path)
    uploaded_sources[image_id] = (source_path, media_type)
    image = catalog.register_upload(
        image_id=image_id,
        image_url=f"/api/uploads/{image_id}",
        source_path=source_path,
        original_width=width,
        original_height=height,
        boxes=[detection.percentage_box() for detection in detections],
    )
    return JSONResponse({"image": image})


@app.get("/api/uploads/{image_id}", include_in_schema=False)
async def uploaded_image(image_id: str) -> FileResponse:
    source = uploaded_sources.get(image_id)
    if source is None or not source[0].is_file():
        raise HTTPException(status_code=404, detail="Uploaded image is no longer available")
    path, media_type = source
    return FileResponse(path, media_type=media_type)


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
                    finding=payload.finding,
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
