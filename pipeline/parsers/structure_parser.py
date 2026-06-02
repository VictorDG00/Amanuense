from __future__ import annotations
import re
from dataclasses import dataclass, field
from .bcb_patterns import (
    ARTIGO_RE, PARAGRAFO_RE, PARAGRAFO_UNICO_RE,
    INCISO_RE, ALINEA_RE,
)


@dataclass
class ParsedAlinea:
    letter: str
    text: str


@dataclass
class ParsedInciso:
    numeral: str
    text: str
    alineas: list[ParsedAlinea] = field(default_factory=list)


@dataclass
class ParsedParagrafo:
    number: str  # "1", "2", "unico"
    text: str
    incisos: list[ParsedInciso] = field(default_factory=list)


@dataclass
class ParsedArtigo:
    number: str          # "1", "2", "15-A"
    header: str          # "Art. 1º"
    text: str            # full raw text of the article
    paragrafos: list[ParsedParagrafo] = field(default_factory=list)
    incisos: list[ParsedInciso] = field(default_factory=list)
    alineas: list[ParsedAlinea] = field(default_factory=list)


@dataclass
class ParsedDocument:
    document_id: str
    artigos: list[ParsedArtigo] = field(default_factory=list)


def _clean_text(text: str) -> str:
    text = text.strip()
    # Merge hyphenated line breaks
    text = re.sub(r'(\w)-\n(\w)', r'\1\2', text)
    # Normalize excessive blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text


def parse_document(document_id: str, markdown_text: str) -> ParsedDocument:
    text = _clean_text(markdown_text)
    doc = ParsedDocument(document_id=document_id)

    for match in ARTIGO_RE.finditer(text):
        number_raw = match.group(1).rstrip("º°").strip()
        artigo_text = _clean_text(match.group(2))

        artigo = ParsedArtigo(
            number=number_raw,
            header=f"Art. {match.group(1)}",
            text=artigo_text,
        )

        # Extract parágrafos únicos first (before numbered)
        for pum in PARAGRAFO_UNICO_RE.finditer(artigo_text):
            artigo.paragrafos.append(ParsedParagrafo(
                number="unico",
                text=_clean_text(pum.group(1)),
            ))

        # Extract numbered parágrafos
        for pm in PARAGRAFO_RE.finditer(artigo_text):
            artigo.paragrafos.append(ParsedParagrafo(
                number=pm.group(1),
                text=_clean_text(pm.group(2)),
            ))

        # Extract incisos (with nested alíneas)
        for im in INCISO_RE.finditer(artigo_text):
            inciso_text = _clean_text(im.group(2))
            inciso = ParsedInciso(numeral=im.group(1), text=inciso_text)
            for am in ALINEA_RE.finditer(inciso_text):
                inciso.alineas.append(ParsedAlinea(
                    letter=am.group(1),
                    text=_clean_text(am.group(2)),
                ))
            artigo.incisos.append(inciso)

        doc.artigos.append(artigo)

    return doc
