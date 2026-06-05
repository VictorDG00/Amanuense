import re

# ── Structure Extraction ────────────────────────────────────────────────────────

# Primary article header — "Art. 1º" or "Art. 1°", optional dash + content
ARTIGO_RE = re.compile(
    r'^Art\.\s*(\d+(?:-[A-Z])?[º°]?)\s*(?:[–\-—]\s*)?(.+?)(?=\nArt\.|\nSeção|\nCapítulo|\nDISPOSIÇÕES|\Z)',
    re.MULTILINE | re.DOTALL,
)

# Numbered paragraphs: "§ 1º" or "§ 1°"
PARAGRAFO_RE = re.compile(
    r'§\s*(\d+)[º°]?\s*(?:[–\-—]\s*)?(.+?)(?=\n§|\nArt\.|\Z)',
    re.MULTILINE | re.DOTALL,
)

# Parágrafo único
PARAGRAFO_UNICO_RE = re.compile(
    r'Parágrafo\s+[Úú]nico\s*(?:[.:\-–—]\s*)?(.+?)(?=\nArt\.|\n§|\Z)',
    re.MULTILINE | re.DOTALL,
)

# Incisos — Roman numerals + dash/em-dash
_ROMAN = r'(?:I{1,3}|IV|VI{0,3}|IX|X{1,3}|XI{0,3}|XIV|XV|XVI{0,3}|XIX|XX{1,2}|XXI{0,3}|XXIV|XXV)'
INCISO_RE = re.compile(
    rf'^({_ROMAN})\s+[–\-—]\s+(.+?)(?=\n{_ROMAN}\s+[–\-—]|\n§|\nArt\.|\Z)',
    re.MULTILINE | re.DOTALL,
)

# Alíneas — "a)" format
ALINEA_RE = re.compile(
    r'^([a-z])\)\s+(.+?)(?=\n[a-z]\)\s|\n§|\nArt\.|\Z)',
    re.MULTILINE | re.DOTALL,
)

# Section / chapter headers
SECAO_RE = re.compile(
    rf'^(?:Seção\s+({_ROMAN})|Capítulo\s+({_ROMAN}))\s*[–\-—]?\s*(.+?)$',
    re.MULTILINE,
)

# ── Revocation Patterns ─────────────────────────────────────────────────────────

REVOGA_EXPRESSAMENTE_PATTERNS: list[re.Pattern] = [
    # "Ficam revogados o art. X da Resolução Y"
    re.compile(
        r'(?:fica[m]?|são|é)\s+revogad[ao]s?\s+(?:o|a|os|as)?\s*'
        r'(?:Resolução|Circular|Instrução|Portaria|Deliberação|art\.|§|inciso|alínea)'
        r'[\w\s,eº°\.\/]+',
        re.IGNORECASE,
    ),
    # "Esta Resolução revoga ..."
    re.compile(
        r'(?:esta|este|a\s+presente)\s+(?:Resolução|Circular|Instrução|Portaria)\s+revoga',
        re.IGNORECASE,
    ),
    # "revogam-se os arts. X, Y e Z" (arts. = plural of art.)
    re.compile(
        r'revogam-se\s+(?:o|a|os|as)?\s*(?:arts?\.|§|incisos?|alíneas?)',
        re.IGNORECASE,
    ),
    # "A partir de [data], fica revogad..."
    re.compile(
        r'a\s+partir\s+de.{0,50}fica[m]?\s+revogad[ao]s?',
        re.IGNORECASE,
    ),
]

REVOGA_PARCIALMENTE_PATTERNS: list[re.Pattern] = [
    # "fica alterado/alterada o art. X / a alínea X"
    re.compile(
        r'(?:fica[m]?|são|é)\s+alterad[ao]s?\s+(?:o|a|os|as)?\s*(?:arts?\.|§|incisos?|alíneas?)',
        re.IGNORECASE,
    ),
    # "dá nova redação ao art. X"
    re.compile(
        r'dá\s+nova\s+redação\s+(?:ao|à|aos|às)\s*(?:art\.|§|inciso|caput|parágrafo)',
        re.IGNORECASE,
    ),
    # "passa a vigorar com a seguinte redação"
    re.compile(
        r'passa\s+a\s+vigorar\s+com\s+a\s+seguinte\s+redação',
        re.IGNORECASE,
    ),
    # "fica acrescido o § X" / "acrescenta-se o inciso"
    re.compile(
        r'(?:fica[m]?\s+acrescido[sa]?|acrescenta[m]?-se)\s+(?:o|a|os|as)?\s*'
        r'(?:art\.|§|inciso|alínea|parágrafo)',
        re.IGNORECASE,
    ),
    # "fica suprimido o inciso X"
    re.compile(
        r'fica[m]?\s+suprimido[sa]?\s+(?:o|a|os|as)?\s*(?:art\.|§|inciso|alínea)',
        re.IGNORECASE,
    ),
]

SUSPENDE_PATTERNS: list[re.Pattern] = [
    re.compile(
        r'(?:fica[m]?|são)\s+suspenso[sa]?\s+(?:os\s+efeitos\s+(?:d[ao]|de))?',
        re.IGNORECASE,
    ),
    re.compile(
        r'suspende\s+(?:a\s+eficácia|os\s+efeitos|a\s+vigência)\s+(?:d[ao])',
        re.IGNORECASE,
    ),
]

# Location marker: revocation clauses typically appear in "Disposições Finais"
DISPOSICOES_FINAIS_RE = re.compile(
    r'(?:Disposições?\s+(?:Finais?|Transitórias?|Gerais?)|DISPOSIÇÕES?\s+FINAIS?)',
    re.IGNORECASE,
)

# Exception clauses that qualify a revocation — always flag review_required
EXCECAO_RE = re.compile(
    r'\b(?:exceto|ressalvad[ao]|com\s+exceção|salvo\s+o\s+disposto|não\s+se\s+aplicando)\b',
    re.IGNORECASE,
)

# Anaphoric references — flag for LLM resolution
ANAFORA_RE = re.compile(
    r'\b(?:mencionad[ao]\s+no\s+artigo\s+anterior|referid[ao]\s+acima|'
    r'supracitad[ao]|já\s+referid[ao]|o\s+artigo\s+anterior)\b',
    re.IGNORECASE,
)

# ── Cross-Document Reference Extraction ─────────────────────────────────────────

# Captures "Art. N" with optional document reference: "da Resolução BCB nº 1/2020"
CROSS_REF_RE = re.compile(
    r'(?:arts?\.\s*(\d+(?:-[A-Z])?)[º°]?'
    r'(?:\s*[,e]\s*(?:arts?\.)?\s*\d+)*)'
    r'(?:\s+(?:d[ao]|da|do)\s+'
    r'(?:Resolução|Circular|Instrução\s+Normativa?|Portaria|Deliberação)\s+'
    r'(?:BCB\s*|CMN\s*)?(?:n[º°]?\s*)?(\d+[\./]\d{2,4}|\d+))?',
    re.IGNORECASE,
)

# Detects norm that "regulamenta" another norm
REGULAMENTA_RE = re.compile(
    r'regulamenta(?:ndo|r|m)?\s+'
    r'(?:o\s+disposto\s+(?:n[ao]|em|na|no)\s+|a\s+|o\s+)?'
    r'(?:Resolução|Circular|Instrução|Portaria|Lei)',
    re.IGNORECASE,
)

# Explicit legal definitions: "considera-se X" / "entende-se por X" / "denomina-se X"
DEFINICAO_RE = re.compile(
    r'(?:considera[m]?-se|entende[m]?-se\s+por|significa[m]?|'
    r'denomina[m]?-se|é\s+(?:o|a)\s+(?:conjunto|processo|sistema|mecanismo|serviço|meio))'
    r'\s+["“]?([A-ZÁÉÍÓÚÂÊÎÔÛÃÕÇ][^\n”"]{3,80})',
    re.IGNORECASE,
)

# Normative deadlines: "prazo de N dias úteis", "até 10 segundos", "D+0", "D+1"
PRAZO_RE = re.compile(
    r'(?:'
    r'prazo\s+(?:máximo\s+)?de\s+(\d+(?:[,.]\d+)?)\s+'
    r'(segundos?|minutos?|horas?|dias?\s+(?:úteis?|corridos?|dias?)?|meses?|anos?)'
    r'|até\s+(\d+(?:[,.]\d+)?)\s+'
    r'(segundos?|minutos?|horas?|dias?\s+(?:úteis?|corridos?)?|meses?)'
    r'|em\s+até\s+(\d+(?:[,.]\d+)?)\s+'
    r'(segundos?|minutos?|horas?|dias?\s+(?:úteis?|corridos?)?)'
    r'|(D\+\d+)'
    r')',
    re.IGNORECASE,
)
