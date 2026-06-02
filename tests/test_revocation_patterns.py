import pytest
from pipeline.parsers.bcb_patterns import (
    REVOGA_EXPRESSAMENTE_PATTERNS,
    REVOGA_PARCIALMENTE_PATTERNS,
    SUSPENDE_PATTERNS,
    EXCECAO_RE,
    ANAFORA_RE,
)

EXPRESS_REVOCATION_FIXTURES = [
    "Ficam revogados o art. 5º e o § 2º do art. 12 da Resolução BCB nº 1, de 2020.",
    "Fica revogada a Circular nº 3.952, de 2019, a partir de 1º de novembro de 2021.",
    "Esta Resolução revoga a Circular BCB nº 4.027, de 12 de novembro de 2020.",
    "São revogados os incisos I e II do art. 3º da Resolução BCB nº 1, de 2020.",
    "Revogam-se os arts. 10 e 11 da presente Resolução.",
    "A presente Circular revoga, integralmente, a Circular BCB nº 3.500, de 2011.",
    "Ficam revogadas as alíneas a e b do inciso II do art. 7º da Resolução BCB nº 1.",
    "A partir de 1º de março de 2022, ficam revogados os §§ 1º e 2º do art. 15.",
]

PARTIAL_REVOCATION_FIXTURES = [
    "Fica alterado o art. 3º da Resolução BCB nº 1, de 2020, com a seguinte redação:",
    "O art. 7º da Resolução BCB nº 1, de 2020, passa a vigorar com a seguinte redação:",
    "Dá nova redação ao art. 15 da Circular BCB nº 3.952, de 2019.",
    "Fica acrescido o inciso III ao art. 3º da Resolução BCB nº 1, de 2020.",
    "Ficam suprimidos os incisos IV e V do art. 8º da Resolução BCB nº 1, de 2020.",
    "O § 3º do art. 22 da Resolução BCB nº 1 passa a vigorar com a seguinte redação:",
    "Dá nova redação ao caput do art. 18 da Circular BCB nº 4.027.",
    "Ficam acrescidos os §§ 4º e 5º ao art. 26 da Resolução BCB nº 1.",
    "Fica alterada a alínea c do inciso I do art. 10 da Circular BCB nº 3.952.",
]

SUSPENSION_FIXTURES = [
    "Ficam suspensos os efeitos do art. 12 da Resolução BCB nº 1.",
    "Ficam suspensos os efeitos da Circular BCB nº 3.952 até deliberação ulterior.",
]

NON_REVOCATION_FIXTURES = [
    "O participante direto é o detentor de conta PI no BCB.",
    "O PSP deve autenticar a transação em até 10 segundos.",
    "Art. 5º As transações Pix são liquidadas em tempo real.",
    "É vedada a cobrança de tarifas em transferências Pix entre pessoas físicas.",
    "O Banco Central do Brasil regulamentará os procedimentos de adesão.",
    "Os participantes devem cumprir os requisitos estabelecidos neste Regulamento.",
    "A liquidação é realizada na conta PI do participante direto.",
]


@pytest.mark.parametrize("text", EXPRESS_REVOCATION_FIXTURES)
def test_express_revocation_detected(text: str) -> None:
    matched = any(p.search(text) for p in REVOGA_EXPRESSAMENTE_PATTERNS)
    assert matched, f"Expected express revocation match in: {text!r}"


@pytest.mark.parametrize("text", PARTIAL_REVOCATION_FIXTURES)
def test_partial_revocation_detected(text: str) -> None:
    matched = any(p.search(text) for p in REVOGA_PARCIALMENTE_PATTERNS)
    assert matched, f"Expected partial revocation match in: {text!r}"


@pytest.mark.parametrize("text", SUSPENSION_FIXTURES)
def test_suspension_detected(text: str) -> None:
    matched = any(p.search(text) for p in SUSPENDE_PATTERNS)
    assert matched, f"Expected suspension match in: {text!r}"


@pytest.mark.parametrize("text", NON_REVOCATION_FIXTURES)
def test_no_false_positives_express(text: str) -> None:
    matched = any(p.search(text) for p in REVOGA_EXPRESSAMENTE_PATTERNS)
    assert not matched, f"Unexpected express revocation match in: {text!r}"


@pytest.mark.parametrize("text", NON_REVOCATION_FIXTURES)
def test_no_false_positives_partial(text: str) -> None:
    matched = any(p.search(text) for p in REVOGA_PARCIALMENTE_PATTERNS)
    assert not matched, f"Unexpected partial revocation match in: {text!r}"


def test_exception_clause_detected() -> None:
    clause = "Ficam revogados os arts. 10 e 11, exceto no que tange ao disposto no § 3º."
    assert EXCECAO_RE.search(clause)


def test_ressalvado_detected() -> None:
    clause = "Fica revogada a Circular BCB nº 3.952, ressalvado o disposto no art. 7º."
    assert EXCECAO_RE.search(clause)


def test_anaphora_detected() -> None:
    clause = "Fica revogada a Circular mencionada no artigo anterior."
    assert ANAFORA_RE.search(clause)


def test_no_false_anaphora() -> None:
    normal = "O participante direto é responsável pela liquidação."
    assert not ANAFORA_RE.search(normal)
