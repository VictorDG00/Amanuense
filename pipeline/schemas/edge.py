from enum import Enum
from typing import Optional, Literal
from pydantic import BaseModel, model_validator


class EdgeType(str, Enum):
    REVOGA_EXPRESSAMENTE = "revoga_expressamente"
    REVOGA_PARCIALMENTE = "revoga_parcialmente"
    SUSPENDE = "suspende"
    REGULAMENTA = "regulamenta"
    SUBORDINA_SE_A = "subordina_se_a"
    ALTERA = "altera"
    REMETE_A = "remete_a"
    REMETE_A_EXTERNO = "remete_a_externo"
    DEFINE = "define"
    EXCEPCIONA = "excepciona"
    COMPLEMENTA = "complementa"
    IMPLEMENTA = "implementa"
    CITA = "cita"
    OBRIGA = "obriga"
    PERMITE = "permite"
    PROIBE = "proibe"
    ATRIBUI_RESPONSABILIDADE = "atribui_responsabilidade"
    APLICA_A = "aplica_a"
    CONDICIONA = "condiciona"
    SUCEDE = "sucede"
    ORIGINOU_SE_DE = "originou_se_de"
    CONSOLIDA = "consolida"
    TRANSITORIAMENTE_APLICAVEL = "transitoriamente_aplicavel"
    TENSIONA = "tensiona"


EDGE_DEFAULT_WEIGHTS: dict[EdgeType, float] = {
    EdgeType.REVOGA_EXPRESSAMENTE: 1.0,
    EdgeType.SUSPENDE: 0.95,
    EdgeType.SUCEDE: 0.9,
    EdgeType.OBRIGA: 0.9,
    EdgeType.PROIBE: 0.9,
    EdgeType.REGULAMENTA: 0.9,
    EdgeType.REVOGA_PARCIALMENTE: 0.85,
    EdgeType.SUBORDINA_SE_A: 0.85,
    EdgeType.ATRIBUI_RESPONSABILIDADE: 0.85,
    EdgeType.APLICA_A: 0.8,
    EdgeType.DEFINE: 0.8,
    EdgeType.CONSOLIDA: 0.8,
    EdgeType.ALTERA: 0.8,
    EdgeType.EXCEPCIONA: 0.75,
    EdgeType.CONDICIONA: 0.75,
    EdgeType.REMETE_A: 0.7,
    EdgeType.REMETE_A_EXTERNO: 0.7,
    EdgeType.IMPLEMENTA: 0.7,
    EdgeType.PERMITE: 0.7,
    EdgeType.ORIGINOU_SE_DE: 0.7,
    EdgeType.COMPLEMENTA: 0.6,
    EdgeType.TRANSITORIAMENTE_APLICAVEL: 0.6,
    EdgeType.TENSIONA: 0.6,
    EdgeType.CITA: 0.5,
}

REVOCATION_EDGE_TYPES = {
    EdgeType.REVOGA_EXPRESSAMENTE,
    EdgeType.REVOGA_PARCIALMENTE,
    EdgeType.SUSPENDE,
}


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    type: EdgeType
    weight: float
    direction: Literal["forward"] = "forward"
    implicit: bool = False
    confidence: Optional[float] = None
    textEvidence: Optional[str] = None
    artigos: list[str] = []
    dataEfeito: Optional[str] = None
    description: Optional[str] = None
    review_required: bool = False
    deprecated: bool = False
    stale: bool = False

    @model_validator(mode="after")
    def no_self_reference(self) -> "GraphEdge":
        if self.source == self.target:
            raise ValueError("Edge source and target cannot be the same node")
        return self

    @model_validator(mode="after")
    def implicit_requires_confidence(self) -> "GraphEdge":
        if self.implicit and self.confidence is None:
            raise ValueError("Implicit edges must have a confidence score")
        return self
