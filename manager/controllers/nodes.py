from fastapi import APIRouter, Depends
from fastapi_cache.decorator import cache

from manager.models.config_models import ExperimentConfig
from manager.models.schemas import ApiResponse, NodeStatus
from manager.services.indicator_service import compute_indicators
from manager.controllers.metrics import get_metrics_service
from manager.services.metrics_service import MetricsService
from manager.services.node_service import NodeService, node_service

router = APIRouter(prefix="/nodes")


def get_node_service() -> NodeService:
    return node_service


@router.post("/start")
async def start_nodes(
    config: ExperimentConfig | None = None,
    metrics_svc: MetricsService = Depends(get_metrics_service),
    node_svc: NodeService = Depends(get_node_service),
):
    experiment_config = config or ExperimentConfig()
    metrics_svc.set_experiment_config(experiment_config)
    await node_svc.start_nodes(experiment_config)
    return ApiResponse(status="started", data=experiment_config.model_dump())


@router.post("/stop")
async def stop_nodes(node_svc: NodeService = Depends(get_node_service)):
    await node_svc.stop_nodes()
    return ApiResponse(status="stopped")


@router.post("/config/indicators")
async def get_config_indicators(config: ExperimentConfig):
    return compute_indicators(config)


@router.get("/status", response_model=list[NodeStatus])
@cache(expire=5)
async def get_status(node_svc: NodeService = Depends(get_node_service)):
    return await node_svc.get_status()
