from __future__ import annotations
import hashlib
import re
import unicodedata
from decimal import Decimal

_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
_ROMAN_RE = re.compile(r"^[IVXLCDM]+$")

# Parágrafos ordenam-se depois dos incisos do caput sob o mesmo artigo:
# § N → 500 + N. "Parágrafo único" fica depois de qualquer § numerado.
PARAGRAFO_ORDEM_OFFSET = Decimal("500")
PARAGRAFO_UNICO_ORDEM = Decimal("999")


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


def doc_id_from_node(node_id: str) -> str:
    """Extract the doc_id from a node ID (e.g. 'art:resolucao-bcb:3' → 'resolucao-bcb')."""
    parts = node_id.split(":", 2)
    return parts[1] if len(parts) >= 2 else ""


def edge_id(source: str, edge_type: str, target: str) -> str:
    raw = f"{source}--{edge_type}--{target}"
    if len(raw) <= 120:
        return raw
    h = hashlib.sha1(raw.encode()).hexdigest()[:8]
    return f"{source[:40]}--{edge_type}--{target[:40]}-{h}"


# ---------------------------------------------------------------------------
# id_canonico — gramática da Base de Legislação Estruturada
#
# Caminho completo do dispositivo, segmentos unidos por "_", somente [a-z0-9]
# dentro de cada segmento. Prefixos fixos: art, par, inc, ali, ite, sub.
# Romanos → arábicos (III → 3); ordinais sem símbolo (5º → 5); sufixos
# alfabéticos minúsculos sem hífen (55-A → art55a); parágrafo único → parun.
# ---------------------------------------------------------------------------


def roman_to_int(numeral: str) -> int:
    """Converte numeral romano (I..MMM) em inteiro. Levanta ValueError se inválido."""
    numeral = numeral.strip().upper()
    if not _ROMAN_RE.match(numeral):
        raise ValueError(f"Numeral romano inválido: {numeral!r}")
    total = 0
    prev = 0
    for char in reversed(numeral):
        value = _ROMAN_VALUES[char]
        total += value if value >= prev else -value
        prev = max(prev, value)
    return total


def _split_sufixo(numero: str) -> tuple[str, str]:
    """'55-A' → ('55', 'a'); '5º' → ('5', ''); 'I-A' → ('I', 'a')."""
    numero = numero.strip().rstrip(".").rstrip("º°").strip()
    m = re.match(r"^([0-9]+|[IVXLCDMivxlcdm]+)\s*-\s*([A-Za-z])$", numero)
    if m:
        return m.group(1), m.group(2).lower()
    return numero, ""


def canon_artigo(numero: str) -> str:
    """'65' → 'art65'; '5º' → 'art5'; '55-A' → 'art55a'."""
    base, sufixo = _split_sufixo(numero)
    return f"art{int(base)}{sufixo}"


def canon_paragrafo(pai: str, par: str) -> str:
    """('art7', 'un') → 'art7_parun'; ('art5', '2º') → 'art5_par2'."""
    if par.strip().lower() in ("un", "unico", "único"):
        return f"{pai}_parun"
    base, sufixo = _split_sufixo(par)
    return f"{pai}_par{int(base)}{sufixo}"


def canon_inciso(pai: str, numeral: str) -> str:
    """('art65', 'I-A') → 'art65_inc1a'; ('art5', 'III') → 'art5_inc3'."""
    base, sufixo = _split_sufixo(numeral)
    return f"{pai}_inc{roman_to_int(base)}{sufixo}"


def canon_alinea(pai: str, letra: str) -> str:
    """('art5_par2_inc3', 'b') → 'art5_par2_inc3_alib'."""
    return f"{pai}_ali{letra.strip().rstrip(')').lower()}"


def canon_item(pai: str, numero: str) -> str:
    """('..._alia', '1') → '..._alia_ite1'."""
    base, sufixo = _split_sufixo(numero)
    return f"{pai}_ite{int(base)}{sufixo}"


def canon_subitem(pai: str, numero: str) -> str:
    """('..._ite1', '1.1') → '..._ite1_sub11' (pontos removidos)."""
    digits = re.sub(r"[^0-9]", "", numero)
    return f"{pai}_sub{digits}"


def ordem_sequencial(numero: str) -> Decimal:
    """Ordem NUMERIC do dispositivo: '55' → 55; '55-A' → 55.01; 'I-A' → 1.01.

    Dispositivos acrescidos (sufixo -A, -B...) entram entre os vizinhos sem
    renumerar: o sufixo vira fração (A=0.01, B=0.02...). 'un' (parágrafo
    único) → PARAGRAFO_UNICO_ORDEM. Subitens '1.1' → Decimal('1.1').
    """
    numero = numero.strip()
    if numero.lower() in ("un", "unico", "único"):
        return PARAGRAFO_UNICO_ORDEM
    if re.match(r"^\d+\.\d+$", numero):
        return Decimal(numero)
    base, sufixo = _split_sufixo(numero)
    valor = roman_to_int(base) if _ROMAN_RE.match(base.upper()) and not base.isdigit() else int(base)
    if sufixo:
        return Decimal(valor) + Decimal(ord(sufixo) - ord("a") + 1) / Decimal(100)
    return Decimal(valor)


def disp_node_id(doc_id: str, id_canonico: str) -> str:
    """ID de nó do grafo para um dispositivo da base: 'disp:{doc_id}:{id_canonico}'."""
    return f"disp:{doc_id}:{id_canonico}"


def urn_lexml(
    autoridade: str,
    tipo: str,
    ano: int,
    numero: str | None,
    doc_id: str,
    esfera: str = "federal",
) -> str:
    """URN LexML simplificada e estável: 'urn:lex:br:banco.central;resolucao:2020;1'.

    Sem número oficial, usa o slug do doc_id como discriminador para manter
    o UNIQUE de norma.urn_lexml.
    """
    autoridade_slug = _slug(autoridade).replace("-", ".") or esfera
    tipo_slug = _slug(tipo).replace("-", ".")
    discriminador = numero.strip() if numero else _slug(doc_id)
    return f"urn:lex:br:{autoridade_slug};{tipo_slug}:{ano};{discriminador}"
