from enum import Enum
from typing import Optional
from datetime import date
from pydantic import BaseModel, Field, model_validator


class NodeType(str, Enum):
    NORMA = "norma"
    ARTIGO = "artigo"
    INCISO = "inciso"
    PARAGRAFO = "paragrafo"
    DEFINICAO = "definicao"
    SANCAO = "sancao"
    INSTITUTO = "instituto"
    PAPEL = "papel"
    PRAZO = "prazo"
    TESE = "tese"
    JURISPRUDENCIA = "jurisprudencia"
    ENTIDADE = "entidade"
    VERSAO = "versao"
    CONSULTA_PUBLICA = "consulta_publica"
    EXPOSICAO_MOTIVOS = "exposicao_motivos"


NORMATIVE_TYPES = {
    NodeType.NORMA, NodeType.ARTIGO, NodeType.INCISO,
    NodeType.PARAGRAFO, NodeType.DEFINICAO, NodeType.SANCAO,
}


class VigencyStatus(str, Enum):
    VIGENTE = "vigente"
    REVOGADO = "revogado"
    SUSPENSO = "suspenso"
    ALTERADO = "alterado"


class NormativeLayer(str, Enum):
    CF = "constituicao_federal"
    LEI_COMPLEMENTAR = "lei_complementar"
    LEI_ORDINARIA = "lei_ordinaria"
    RESOLUCAO = "resolucao"
    CIRCULAR = "circular"
    INSTRUCAO_NORMATIVA = "instrucao_normativa"
    MANUAL = "manual"


LAYER_LEVELS: dict[NormativeLayer, int] = {
    NormativeLayer.CF: 1,
    NormativeLayer.LEI_COMPLEMENTAR: 2,
    NormativeLayer.LEI_ORDINARIA: 2,
    NormativeLayer.RESOLUCAO: 3,
    NormativeLayer.CIRCULAR: 4,
    NormativeLayer.INSTRUCAO_NORMATIVA: 5,
    NormativeLayer.MANUAL: 6,
}


class VigenciaMeta(BaseModel):
    dataInicio: date
    dataFim: Optional[date] = None
    status: VigencyStatus
    versaoAtiva: Optional[str] = None
    ultimaVerificacao: date

    @model_validator(mode="after")
    def validate_dates(self) -> "VigenciaMeta":
        if self.dataFim is not None and self.dataFim < self.dataInicio:
            raise ValueError("dataFim cannot be before dataInicio")
        return self


class NormaMeta(BaseModel):
    autoridade: str
    tipoNorma: str
    numero: Optional[str] = None
    ano: Optional[int] = None
    dispositivo: Optional[str] = None


class GraphNode(BaseModel):
    id: str
    type: NodeType
    name: str
    summary: str
    tags: list[str] = Field(default_factory=list)
    normativeLayer: Optional[NormativeLayer] = None
    sourceDocument: Optional[str] = None
    articleNumber: Optional[str] = None
    vigenciaMeta: Optional[VigenciaMeta] = None
    normaMeta: Optional[NormaMeta] = None
    review_required: bool = False
    review_notes: Optional[str] = None

    @model_validator(mode="after")
    def require_vigencia_for_normative(self) -> "GraphNode":
        if self.type in NORMATIVE_TYPES and self.vigenciaMeta is None:
            raise ValueError(f"Node type '{self.type}' requires vigenciaMeta")
        return self
