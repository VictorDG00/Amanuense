import pytest
from pipeline.parsers.structure_parser import parse_document

SAMPLE_ARTIGOS = """
Art. 1º Esta Resolução institui o arranjo de pagamentos denominado Pix e aprova o seu Regulamento.

Art. 2º O Pix é o arranjo de pagamentos instantâneos do Banco Central do Brasil (BCB).

Parágrafo único. Os pagamentos Pix são processados em tempo real, todos os dias do ano.

Art. 3º Os participantes do arranjo Pix são classificados em:
I – participante direto;
II – participante indireto; e
III – prestador de serviço de iniciação de transação de pagamento.
§ 1º O participante direto é o detentor de conta PI no BCB.
§ 2º O participante indireto acessa o Pix por meio de participante direto.

Art. 4º O BCB é o gestor do arranjo de pagamentos Pix.
§ 1º O BCB poderá editar normas complementares.
§ 2º O BCB divulgará o regulamento em seu sítio na internet.
"""


def test_parse_artigo_count() -> None:
    doc = parse_document("test-doc", SAMPLE_ARTIGOS)
    assert len(doc.artigos) == 4


def test_artigo_numbers() -> None:
    doc = parse_document("test-doc", SAMPLE_ARTIGOS)
    numbers = {a.number for a in doc.artigos}
    assert {"1", "2", "3", "4"}.issubset(numbers)


def test_artigo_header_format() -> None:
    doc = parse_document("test-doc", SAMPLE_ARTIGOS)
    art1 = next(a for a in doc.artigos if a.number == "1")
    assert art1.header.startswith("Art.")


def test_inciso_extraction() -> None:
    doc = parse_document("test-doc", SAMPLE_ARTIGOS)
    art3 = next(a for a in doc.artigos if a.number == "3")
    assert len(art3.incisos) == 3
    numerals = {i.numeral for i in art3.incisos}
    assert {"I", "II", "III"}.issubset(numerals)


def test_paragrafo_extraction() -> None:
    doc = parse_document("test-doc", SAMPLE_ARTIGOS)
    art3 = next(a for a in doc.artigos if a.number == "3")
    numbered = [p for p in art3.paragrafos if p.number != "unico"]
    assert len(numbered) >= 2


def test_paragrafo_unico() -> None:
    doc = parse_document("test-doc", SAMPLE_ARTIGOS)
    art2 = next(a for a in doc.artigos if a.number == "2")
    unico = next((p for p in art2.paragrafos if p.number == "unico"), None)
    assert unico is not None
    assert "tempo real" in unico.text.lower()


def test_empty_document() -> None:
    doc = parse_document("empty", "")
    assert doc.artigos == []


def test_document_id_preserved() -> None:
    doc = parse_document("my-doc-id", SAMPLE_ARTIGOS)
    assert doc.document_id == "my-doc-id"
