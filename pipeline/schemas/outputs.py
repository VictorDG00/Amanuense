from datetime import datetime, date
from typing import Optional, Literal
from pydantic import BaseModel
from .node import VigencyStatus


class VigencyIndexEntry(BaseModel):
    nodeId: str
    normId: str
    status: VigencyStatus
    dataInicio: date
    dataFim: Optional[date] = None
    affectedByEdgeIds: list[str] = []
    ultimaVerificacao: date


class VigencyIndex(BaseModel):
    generatedAt: datetime
    corpus: str
    total: int
    byStatus: dict[str, int]
    entries: list[VigencyIndexEntry]


class DiffLogEntry(BaseModel):
    timestamp: datetime
    changeType: Literal["add", "modify", "revoke", "suspend", "alter"]
    affectedNodeIds: list[str]
    affectedEdgeIds: list[str]
    description: str
    corpusFile: str
    impacto: Literal["alto", "medio", "baixo"] = "medio"


class DiffLog(BaseModel):
    generatedAt: datetime
    entries: list[DiffLogEntry]


class CorpusTextVersionEntry(BaseModel):
    vigencia: str
    textoCompleto: str
    nota: Optional[str] = None


class CorpusTextEntry(BaseModel):
    textoCompleto: str
    caput: Optional[str] = None
    incisos: dict[str, str] = {}
    paragrafos: dict[str, str] = {}
    alineas: dict[str, str] = {}
    versoes: dict[str, CorpusTextVersionEntry] = {}


class CorpusTexts(BaseModel):
    generatedAt: datetime
    texts: dict[str, CorpusTextEntry]
