from enum import Enum

from pydantic import BaseModel, Field


class TopologyType(str, Enum):
    FULL_MESH = "full_mesh"
    CIRCULANT = "circulant"
    RING_LATTICE = "ring_lattice"
    HYPERCUBE = "hypercube"


class TopologyConfig(BaseModel):
    topology_type: TopologyType = Field(
        default=TopologyType.FULL_MESH, description="Type of network topology to generate"
    )
    degree: int = Field(default=4, ge=2, description="Node degree for circulant graph")
