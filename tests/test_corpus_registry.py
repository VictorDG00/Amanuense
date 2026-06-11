from pipeline.corpus_registry import detect_metadata, load_registry, save_registry


# ── detect_metadata ───────────────────────────────────────────────────────────

def test_detect_resolucao():
    m = detect_metadata("resolucao-bcb-001-2020")
    assert m["type"] == "resolucao"
    assert m["authority"] == "BCB"
    assert m["number"] == "001"
    assert m["year"] == 2020


def test_detect_circular():
    m = detect_metadata("circular-bcb-3952-2019")
    assert m["type"] == "circular"
    assert m["authority"] == "BCB"
    assert m["number"] == "3952"
    assert m["year"] == 2019


def test_detect_instrucao_normativa():
    m = detect_metadata("instrucao-normativa-bcb-50-2020")
    assert m["type"] == "instrucao_normativa"
    assert m["authority"] == "BCB"
    assert m["number"] == "50"
    assert m["year"] == 2020


def test_detect_manual():
    m = detect_metadata("manual-seguranca-pix")
    assert m["type"] == "manual"
    assert m["authority"] == "BCB"
    assert m["number"] is None


def test_detect_lei_ordinaria():
    m = detect_metadata("lei-9613-1998")
    assert m["type"] == "lei_ordinaria"
    assert m["authority"] == "Federal"
    assert m["number"] == "9613"
    assert m["year"] == 1998


def test_detect_lei_complementar():
    m = detect_metadata("lei-complementar-105-2001")
    assert m["type"] == "lei_complementar"
    assert m["number"] == "105"
    assert m["year"] == 2001


def test_detect_fallback_returns_resolucao():
    m = detect_metadata("documento-qualquer-sem-padrao")
    assert m["type"] == "resolucao"
    assert m["authority"] == "BCB"


def test_detect_underscore_is_normalized():
    m = detect_metadata("resolucao_bcb_001_2020")
    assert m["type"] == "resolucao"
    assert m["year"] == 2020


# ── load/save registry ────────────────────────────────────────────────────────

def test_load_empty_registry(tmp_path):
    assert load_registry(tmp_path) == {}


def test_save_and_reload(tmp_path):
    registry = {
        "resolucao-bcb-001-2020": {"type": "resolucao", "authority": "BCB", "year": 2020}
    }
    save_registry(tmp_path, registry)
    loaded = load_registry(tmp_path)
    assert loaded == registry


def test_save_creates_dir(tmp_path):
    nested = tmp_path / "deep" / "corpus"
    save_registry(nested, {"doc": {"type": "manual"}})
    assert (nested / "registry.json").exists()


def test_save_overwrites(tmp_path):
    save_registry(tmp_path, {"doc-a": {"type": "resolucao"}})
    save_registry(tmp_path, {"doc-b": {"type": "circular"}})
    loaded = load_registry(tmp_path)
    assert "doc-a" not in loaded
    assert "doc-b" in loaded
