from datetime import datetime
from typing import Any
from pydantic import BaseModel
from .node import GraphNode
from .edge import GraphEdge


class Layer(BaseModel):
    id: str
    name: str
    normativeLevel: int
    nodeIds: list[str]
    description: str


class TourStep(BaseModel):
    order: int
    title: str
    description: str
    nodeIds: list[str]
    profileTarget: list[str]


class KnowledgeGraph(BaseModel):
    version: str = "1.0"
    generatedAt: datetime
    corpus: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    layers: list[Layer]
    tours: list[TourStep]
    meta: dict[str, Any] = {}
