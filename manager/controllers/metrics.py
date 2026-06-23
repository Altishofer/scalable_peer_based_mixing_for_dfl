import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette import EventSourceResponse

from manager.models.schemas import ApiResponse, MetricPoint
from manager.services.metrics_service import MetricsService, metrics_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/metrics")

# matches node push interval
BATCH_INTERVAL = 1.0


def get_metrics_service() -> MetricsService:
    return metrics_service


@router.get("/history")
async def get_metrics_history(
    offset: int = 0,
    limit: int = 50000,
    svc: MetricsService = Depends(get_metrics_service),
):
    return await svc.get_history_paginated(offset, limit)


@router.get("/sse")
async def metrics_sse(
    request: Request,
    svc: MetricsService = Depends(get_metrics_service),
):
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break

            await asyncio.sleep(BATCH_INTERVAL)

            new_metrics = await svc.pop_all_metrics()
            if new_metrics:
                serialized = [point.model_dump() for point in new_metrics]
                yield {"data": json.dumps(serialized)}

    return EventSourceResponse(event_generator())


@router.get("/clear")
async def clear_metrics(
    output_dir: str | None = None,
    svc: MetricsService = Depends(get_metrics_service),
):
    try:
        target_dir = None
        if output_dir:
            from manager.config import settings

            # path-traversal guard
            target_dir = (settings.METRICS_DIR / output_dir).resolve()
            if not str(target_dir).startswith(str(settings.METRICS_DIR.resolve())):
                raise HTTPException(status_code=400, detail="output_dir must be within metrics directory")
        await svc.clear(target_dir)
        return ApiResponse(status="success", message="Metrics cleared")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to clear metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to clear metrics")


@router.post("/push", response_model=list[MetricPoint])
async def push_metrics(
    new_metrics: list[MetricPoint],
    svc: MetricsService = Depends(get_metrics_service),
):
    try:
        return await svc.push(new_metrics)
    except Exception as e:
        logger.error(f"Failed to store metrics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to store metrics")


@router.get("/highest-round")
async def get_highest_round(svc: MetricsService = Depends(get_metrics_service)):
    highest = await svc.get_highest_round()
    return {"highest_round": highest}


@router.get("/all-completed")
async def get_all_completed(svc: MetricsService = Depends(get_metrics_service)):
    return {"completed": await svc.all_completed()}
