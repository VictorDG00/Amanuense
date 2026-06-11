from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent.parent

CORPUS_DIR = BASE_DIR / os.environ.get("AMANUENSE_CORPUS_DIR", "corpus")
OUTPUT_DIR = BASE_DIR / os.environ.get("AMANUENSE_OUTPUT_DIR", "output")
INTERMEDIATE_DIR = BASE_DIR / os.environ.get("AMANUENSE_INTERMEDIATE_DIR", "intermediate")

CORPUS_RAW_DIR = CORPUS_DIR / "raw"
CORPUS_PARSED_DIR = CORPUS_DIR / "parsed"

IMPLICIT_CONFIDENCE_THRESHOLD = 0.70
IMPLICIT_CONFIDENCE_AUTO_APPROVE = 0.85
MAX_IMPLICIT_EDGES_PER_ARTICLE = 5
VIGENCY_REVIEW_STALENESS_DAYS = 90

# Batch size for implication-analyzer: articles per LLM call
# Set to 1 to use original single-article format (array response)
# Set to 2+ to use batched format (object response keyed by art_id)
IMPLICATION_BATCH_SIZE = 4
