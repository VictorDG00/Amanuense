"""Árvore JSON canônica de uma norma — intermediário entre parsing e carga.

Espelha o modelo da Base de Legislação Estruturada (norma / agrupamento /
dispositivo / dispositivo_versao). Nunca carregar texto direto no banco:
o parser gera esta árvore (testável, diffável, idempotente) e o agente
legislation-loader a aplica via funções fn_* do motor de versionamento.

Diretriz anti-alucinação: todo `texto` aqui vem do parsing da fonte oficial.
Eventos com `confiavel=False` jamais são carregados — vão para a fila de
revisão manual.
"""
from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field

TipoDispositivo = Literal["artigo", "paragrafo", "inciso", "alinea", "item", "subitem"]
TipoAgrupamento = Literal["parte", "livro", "titulo", "capitulo", "secao", "subsecao"]
TipoEvento = Literal["redacao_original", "alteracao", "revogacao", "renumeracao"]


class EventoHistorico(BaseModel):
    """Anotação de histórico extraída do texto compilado.

    Ex.: '(Redação dada pela Resolução BCB nº 30, de 2020)'.
    """

    evento: TipoEvento
    norma_alteradora_ref: Optional[str] = None  # texto bruto da referência
    norma_alteradora_doc_id: Optional[str] = None  # resolvido contra o corpus
    data_efeito: Optional[date] = None
    texto: Optional[str] = None  # None quando evento = revogacao
    confiavel: bool = True  # False → fila de revisão, nunca carregado


class DispositivoCanonico(BaseModel):
    """Identidade + redação original + histórico de um dispositivo."""

    id_canonico: str  # 'art5', 'art5_par2', 'art5_par2_inc3'
    tipo: TipoDispositivo
    rotulo: str  # 'Art. 5º', '§ 2º', 'III', 'a)'
    numero: str  # '5', '2', 'III', 'a', '55-A', 'un'
    ordem_sequencial: str  # Decimal serializado: '5', '55.01', '999'
    texto_original: Optional[str] = None  # None se incluído por norma posterior
    historico: list[EventoHistorico] = Field(default_factory=list)
    filhos: list["DispositivoCanonico"] = Field(default_factory=list)
    review_required: bool = False
    review_notes: Optional[str] = None


class AgrupamentoCanonico(BaseModel):
    """Eixo organizacional acima do artigo (LC 95/1998, art. 10, V)."""

    tipo: TipoAgrupamento
    rotulo: str  # 'Capítulo IX'
    nome: Optional[str] = None  # 'Da Autoridade Nacional...'
    ordem_sequencial: str
    filhos: list["AgrupamentoCanonico"] = Field(default_factory=list)
    artigos: list[str] = Field(default_factory=list)  # id_canonico dos artigos


class ItemRevisao(BaseModel):
    """Trecho que o parser não interpreta com confiança (spec §6)."""

    doc_id: str
    trecho: str
    motivo: str  # 'vide', 'vetado', 'ref_nao_resolvida', 'parse', 'diff_consolidado'...
    id_canonico: Optional[str] = None
    linha: Optional[int] = None


class NormaCanonica(BaseModel):
    """Árvore canônica completa de uma norma, pronta para carga."""

    doc_id: str
    tipo: str  # 'resolucao', 'circular', 'lei_ordinaria'...
    numero: Optional[str] = None
    ano: int
    apelido: str  # = doc_id (mapeamento reverso doc_id ↔ norma)
    urn_lexml: str
    data_publicacao: date
    esfera: str = "federal"
    orgao_emissor: Optional[str] = None
    ementa: Optional[str] = None
    url_fonte_oficial: Optional[str] = None
    agrupamentos: list[AgrupamentoCanonico] = Field(default_factory=list)
    dispositivos: list[DispositivoCanonico] = Field(default_factory=list)  # artigos na raiz
    review_queue: list[ItemRevisao] = Field(default_factory=list)
    review_required: bool = False


def iter_dispositivos(norma: NormaCanonica):
    """Percorre todos os dispositivos da árvore em profundidade (pré-ordem)."""

    def _walk(disp: DispositivoCanonico, pai: Optional[DispositivoCanonico]):
        yield disp, pai
        for filho in disp.filhos:
            yield from _walk(filho, disp)

    for artigo in norma.dispositivos:
        yield from _walk(artigo, None)
