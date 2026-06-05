from __future__ import annotations
import hashlib
import re
import unicodedata


def _slug(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def norma_id(doc_id: str) -> str:
    return f"norma:{doc_id}"


def artigo_id(doc_id: str, art_number: str) -> str:
    n = art_number.rstrip("º°").strip().lower().replace(" ", "-")
    return f"art:{doc_id}:{n}"


def inciso_id(doc_id: str, art_number: str, numeral: str) -> str:
    n = art_number.rstrip("º°").strip().lower().replace(" ", "-")
    return f"inc:{doc_id}:{n}:{numeral.upper()}"


def paragrafo_id(doc_id: str, art_number: str, par: str) -> str:
    n = art_number.rstrip("º°").strip().lower().replace(" ", "-")
    return f"par:{doc_id}:{n}:{par.lower()}"


def definicao_id(doc_id: str, termo: str) -> str:
    return f"def:{doc_id}:{_slug(termo)}"


def papel_id(nome: str) -> str:
    return f"papel:{_slug(nome)}"


def prazo_id(doc_id: str, art_number: str, n: int) -> str:
    a = art_number.rstrip("º°").strip().lower().replace(" ", "-")
    return f"prazo:{doc_id}:{a}:{n}"


def entidade_id(nome: str) -> str:
    return f"ent:{_slug(nome)}"


def versao_id(node_id: str, v: int) -> str:
    return f"{node_id}:v{v}"


def edge_id(source: str, edge_type: str, target: str) -> str:
    raw = f"{source}--{edge_type}--{target}"
    if len(raw) <= 120:
        return raw
    h = hashlib.sha1(raw.encode()).hexdigest()[:8]
    return f"{source[:40]}--{edge_type}--{target[:40]}-{h}"
