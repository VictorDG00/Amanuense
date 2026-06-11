"""Gramática do id_canonico (spec §3) e ordem sequencial NUMERIC."""
from decimal import Decimal

import pytest

from pipeline.utils.id_factory import (
    PARAGRAFO_UNICO_ORDEM,
    canon_alinea,
    canon_artigo,
    canon_inciso,
    canon_item,
    canon_paragrafo,
    canon_subitem,
    disp_node_id,
    ordem_sequencial,
    roman_to_int,
    urn_lexml,
)


class TestRomanToInt:
    def test_basicos(self):
        assert roman_to_int("I") == 1
        assert roman_to_int("IV") == 4
        assert roman_to_int("IX") == 9
        assert roman_to_int("XLV") == 45
        assert roman_to_int("CL") == 150

    def test_minusculo(self):
        assert roman_to_int("iii") == 3

    def test_invalido(self):
        with pytest.raises(ValueError):
            roman_to_int("ABC")
        with pytest.raises(ValueError):
            roman_to_int("")


class TestGramaticaSpec:
    """Tabela de exemplos da especificação, §3."""

    def test_art65(self):
        assert canon_artigo("65") == "art65"

    def test_art65_inc1a(self):
        assert canon_inciso(canon_artigo("65"), "I-A") == "art65_inc1a"

    def test_art5_par2_inc3(self):
        art = canon_artigo("5º")
        par = canon_paragrafo(art, "2º")
        assert canon_inciso(par, "III") == "art5_par2_inc3"

    def test_art5_par2_inc3_alib(self):
        inc = canon_inciso(canon_paragrafo(canon_artigo("5º"), "2º"), "III")
        assert canon_alinea(inc, "b") == "art5_par2_inc3_alib"

    def test_art7_parun(self):
        assert canon_paragrafo(canon_artigo("7º"), "un") == "art7_parun"

    def test_art55a(self):
        assert canon_artigo("55-A") == "art55a"

    def test_alia_ite1_sub11(self):
        ali = canon_alinea("art1_inc1", "a)")
        ite = canon_item(ali, "1")
        assert canon_subitem(ite, "1.1") == "art1_inc1_alia_ite1_sub11"

    def test_artigo_com_ponto(self):
        assert canon_artigo("10.") == "art10"


class TestOrdemSequencial:
    def test_inteiro(self):
        assert ordem_sequencial("55") == Decimal("55")

    def test_sufixo_a(self):
        assert ordem_sequencial("55-A") == Decimal("55.01")

    def test_sufixo_b(self):
        assert ordem_sequencial("5-B") == Decimal("5.02")

    def test_romano(self):
        assert ordem_sequencial("IV") == Decimal("4")

    def test_romano_sufixado(self):
        assert ordem_sequencial("I-A") == Decimal("1.01")

    def test_paragrafo_unico(self):
        assert ordem_sequencial("un") == PARAGRAFO_UNICO_ORDEM

    def test_subitem(self):
        assert ordem_sequencial("1.1") == Decimal("1.1")

    def test_intercalacao_preserva_ordem(self):
        # I < I-A < II — invariante central da spec (§2.7)
        assert ordem_sequencial("I") < ordem_sequencial("I-A") < ordem_sequencial("II")


class TestNodeIdEUrn:
    def test_disp_node_id(self):
        assert (
            disp_node_id("resolucao-bcb-1", "art5_par2_inc3")
            == "disp:resolucao-bcb-1:art5_par2_inc3"
        )

    def test_urn_com_numero(self):
        assert (
            urn_lexml("Banco Central", "resolucao", 2020, "1", "resolucao-bcb-1")
            == "urn:lex:br:banco.central;resolucao:2020;1"
        )

    def test_urn_sem_numero_usa_doc_id(self):
        urn = urn_lexml("BCB", "manual", 2021, None, "manual-pix-2021")
        assert urn.endswith(";manual-pix-2021")
