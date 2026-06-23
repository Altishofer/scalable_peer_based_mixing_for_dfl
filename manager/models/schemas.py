from pydantic import BaseModel


class NodeStatus(BaseModel):
    name: str
    status: str
    started_at: str
    current_round: int = 0


class MetricPoint(BaseModel):
    timestamp: str
    field: str
    name: str
    unit: str
    group: str
    value: float | str
    node: str


class ApiResponse(BaseModel):
    status: str
    message: str = ""
    data: dict | None = None
