"""Parser estrutural → árvore canônica (pilha de contexto + histórico inline)."""
from datetime import date

from pipeline.parsers.canonical_tree import build_canonical_tree
from pipeline.parsers.history_patterns import build_corpus_index, parse_norma_ref
from pipeline.schemas.legislacao import iter_dispositivos

DOC_META = {
    "documentId": "resolucao-bcb-001-2020",
    "authority": "BCB",
    "type": "resolucao",
    "number": "1",
    "year": 2020,
    "dataPublicacao": "2020-08-12",
    "dataVigor": "2020-11-03",
    "description": "Institui o arranjo de pagamentos Pix",
}

ALTERADORA_META = {
    "documentId": "resolucao-bcb-030-2020",
    "authority": "BCB",
    "type": "resolucao",
    "number": "30",
    "year": 2020,
    "dataPublicacao": "2020-10-29",
    "dataVigor": "2020-10-29",
}

MD_BASICO = """\
CAPÍTULO I
DAS DISPOSIÇÕES PRELIMINARES

Art. 1º Esta Resolução institui o arranjo de pagamentos Pix.

Art. 2º Para fins desta Resolução, considera-se:

I - participante: pessoa jurídica autorizada;

II - usuário: pessoa que utiliza o Pix:

a) pagador; e

b) recebedor.

§ 1º O disposto aplica-se aos participantes diretos.

§ 2º Aplicam-se as seguintes regras:

I - liquidação em tempo real; e

II - disponibilidade integral:

a) em qualquer dia:

1. inclusive feriados.

Parágrafo único. Caso omisso será decidido pelo BCB.

Art. 5º-A O participante deve manter canal de atendimento.
"""


def _tree(md: str, extra_docs: list[dict] | None = None):
    index = build_corpus_index([DOC_META] + (extra_docs or []))
    return build_canonical_tree("resolucao-bcb-001-2020", md, DOC_META, index)


class TestEstrutura:
    def test_artigos_na_raiz(self):
        norma = _tree(MD_BASICO)
        ids = [d.id_canonico for d in norma.dispositivos]
        assert ids == ["art1", "art2", "art5a"]

    def test_caput(self):
        norma = _tree(MD_BASICO)
        assert norma.dispositivos[0].texto_original == (
            "Esta Resolução institui o arranjo de pagamentos Pix."
        )

    def test_inciso_do_caput_e_do_paragrafo(self):
        norma = _tree(MD_BASICO)
        todos = {d.id_canonico: (d, p) for d, p in iter_dispositivos(norma)}
        # incisos I e II pendurados direto no artigo (antes dos parágrafos)
        assert todos["art2_inc1"][1].id_canonico == "art2"
        # inciso I do § 2º pendura no parágrafo, não no artigo
        assert todos["art2_par2_inc1"][1].id_canonico == "art2_par2"

    def test_alinea_item(self):
        norma = _tree(MD_BASICO)
        todos = {d.id_canonico for d, _ in iter_dispositivos(norma)}
        assert "art2_inc2_alia" in todos
        assert "art2_inc2_alib" in todos
        assert "art2_par2_inc2_alia_ite1" in todos

    def test_paragrafo_unico_apos_paragrafos_numerados(self):
        # "Parágrafo único" aqui pertence ao art. 2º (ordem 999, depois dos §§)
        norma = _tree(MD_BASICO)
        todos = {d.id_canonico for d, _ in iter_dispositivos(norma)}
        assert "art2_parun" in todos

    def test_artigo_sufixado(self):
        norma = _tree(MD_BASICO)
        art5a = norma.dispositivos[-1]
        assert art5a.id_canonico == "art5a"
        assert art5a.numero == "5-A"

    def test_agrupamento(self):
        norma = _tree(MD_BASICO)
        assert len(norma.agrupamentos) == 1
        cap = norma.agrupamentos[0]
        assert cap.tipo == "capitulo"
        assert cap.nome == "DAS DISPOSIÇÕES PRELIMINARES"
        assert "art1" in cap.artigos


class TestHistorico:
    def test_redacao_dada(self):
        md = (
            "Art. 1º Texto novo do dispositivo. "
            "(Redação dada pela Resolução BCB nº 30, de 2020)\n"
        )
        norma = _tree(md, [ALTERADORA_META])
        art1 = norma.dispositivos[0]
        assert art1.texto_original is None  # redação original desconhecida
        assert len(art1.historico) == 1
        ev = art1.historico[0]
        assert ev.evento == "alteracao"
        assert ev.norma_alteradora_doc_id == "resolucao-bcb-030-2020"
        assert ev.data_efeito == date(2020, 10, 29)
        assert ev.texto == "Texto novo do dispositivo."
        assert ev.confiavel

    def test_incluido_pela(self):
        md = "Art. 2º Dispositivo acrescentado. (Incluído pela Resolução BCB nº 30, de 2020)\n"
        norma = _tree(md, [ALTERADORA_META])
        ev = norma.dispositivos[0].historico[0]
        assert ev.evento == "redacao_original"
        assert ev.norma_alteradora_doc_id == "resolucao-bcb-030-2020"
        assert ev.confiavel

    def test_revogado_pela(self):
        md = "Art. 3º (Revogado pela Resolução BCB nº 30, de 2020)\n"
        norma = _tree(md, [ALTERADORA_META])
        ev = norma.dispositivos[0].historico[0]
        assert ev.evento == "revogacao"
        assert ev.texto is None

    def test_ref_fora_do_corpus_vai_para_fila(self):
        md = "Art. 1º Texto. (Redação dada pela Resolução BCB nº 999, de 2099)\n"
        norma = _tree(md)
        ev = norma.dispositivos[0].historico[0]
        assert not ev.confiavel
        assert any(i.motivo == "ref_nao_resolvida" for i in norma.review_queue)

    def test_vide_nao_interpretado(self):
        md = "Art. 1º Texto vigente. (Vide Resolução BCB nº 50, de 2021)\n"
        norma = _tree(md)
        art1 = norma.dispositivos[0]
        assert art1.historico == []
        assert art1.review_required
        assert any(i.motivo == "nao_interpretar" for i in norma.review_queue)
        assert art1.texto_original == "Texto vigente."


class TestParseNormaRef:
    def test_resolucao_bcb(self):
        ref = parse_norma_ref("Resolução BCB nº 30, de 2020")
        assert ref == {"tipo": "resolucao", "numero": "30", "ano": 2020}

    def test_lei_com_data_completa(self):
        ref = parse_norma_ref("Lei nº 13.853, de 8 de julho de 2019")
        assert ref == {"tipo": "lei_ordinaria", "numero": "13853", "ano": 2019}
