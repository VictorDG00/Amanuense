"""Padrões de extração de histórico inline (spec §4, Etapa 2).

Textos compilados (Planalto e atos BCB consolidados) anotam o histórico junto
ao dispositivo: "(Redação dada pela Resolução BCB nº 30, de 2020)". Estes
padrões transformam as anotações em eventos de versionamento. Anotações não
interpretáveis ((Vide ...), (Vetado), (Vigência)) NUNCA são interpretadas —
vão para a fila de revisão manual (spec §6).
"""
from __future__ import annotations

import re

# "(Redação dada pela Resolução BCB nº 30, de 2020)" / "(Alterado pela ...)"
REDACAO_DADA_RE = re.compile(
    r"\(\s*(?:Redação\s+dada|Alterad[oa])\s+pel[ao]\s+([^)]+?)\s*\)",
    re.IGNORECASE,
)

# "(Incluído pela Lei nº 13.853, de 2019)" / "(Acrescentado pela ...)"
INCLUIDO_RE = re.compile(
    r"\(\s*(?:Incluíd[oa]|Acrescentad[oa]|Acrescid[oa])\s+pel[ao]\s+([^)]+?)\s*\)",
    re.IGNORECASE,
)

# "(Revogado pela Resolução BCB nº 100, de 2021)"
REVOGADO_RE = re.compile(
    r"\(\s*Revogad[oa]\s+pel[ao]\s+([^)]+?)\s*\)",
    re.IGNORECASE,
)

# Anotações que NÃO devem ser interpretadas — fila manual (spec §4/§6).
NAO_INTERPRETAR_RE = re.compile(
    r"\(\s*(Vide[^)]*|Vetad[oa][^)]*|Vigência[^)]*)\s*\)",
    re.IGNORECASE,
)

# Referência a norma dentro da anotação: tipo + número + ano.
# Ex.: "Resolução BCB nº 30, de 2020", "Lei nº 13.853, de 8 de julho de 2019"
NORMA_REF_RE = re.compile(
    r"(Lei\s+Complementar|Lei|Resolução\s+Conjunta|Resolução|Circular|"
    r"Instrução\s+Normativa|Portaria|Decreto|Medida\s+Provisória)"
    r"\s*(?:BCB|CMN|do\s+BCB|do\s+CMN)?\s*"
    r"(?:n[º°.]?\s*)?([\d.]+)"
    r"(?:\s*,?\s*de\s+(?:\d{1,2}[º°]?\s+de\s+\w+\s+de\s+)?(\d{4}))?",
    re.IGNORECASE,
)

# tipo textual da anotação → tipo do registry/manifest
_TIPO_MAP = {
    "lei complementar": "lei_complementar",
    "lei": "lei_ordinaria",
    "resolução conjunta": "resolucao",
    "resolução": "resolucao",
    "circular": "circular",
    "instrução normativa": "instrucao_normativa",
    "portaria": "portaria",
    "decreto": "decreto",
    "medida provisória": "medida_provisoria",
}


def parse_norma_ref(ref_text: str) -> dict | None:
    """Extrai (tipo, numero, ano) de uma referência textual a norma.

    Retorna {"tipo", "numero", "ano"} ou None se a referência não casa.
    O número é normalizado sem pontos de milhar ('13.853' → '13853').
    """
    m = NORMA_REF_RE.search(ref_text)
    if not m:
        return None
    tipo_raw = re.sub(r"\s+", " ", m.group(1).strip().lower())
    numero = m.group(2).replace(".", "")
    ano = int(m.group(3)) if m.group(3) else None
    return {"tipo": _TIPO_MAP.get(tipo_raw, tipo_raw), "numero": numero, "ano": ano}


def build_corpus_index(documents: list[dict]) -> dict[tuple, dict]:
    """Índice (tipo, numero, ano) → documento do manifest, p/ resolver referências."""
    index: dict[tuple, dict] = {}
    for doc in documents:
        numero = str(doc.get("number") or "").replace(".", "").lstrip("0")
        tipo = doc.get("type") or ""
        ano = doc.get("year")
        if numero and tipo and ano:
            index[(tipo, numero, int(ano))] = doc
    return index


def resolve_norma_ref(ref_text: str, corpus_index: dict[tuple, dict]) -> dict | None:
    """Resolve uma referência textual contra o corpus. None se não encontrada."""
    ref = parse_norma_ref(ref_text)
    if not ref or not ref["ano"]:
        return None
    key = (ref["tipo"], ref["numero"].lstrip("0"), ref["ano"])
    return corpus_index.get(key)
