"""Parser estrutural → árvore JSON canônica (spec §4, Etapa 1).

Parsing linha a linha com pilha de contexto: ao encontrar um inciso, o pai é
o último parágrafo aberto, senão o artigo corrente — e assim por diante
(LC 95/1998, art. 10). Nunca carrega direto no banco: gera a NormaCanonica,
que o legislation-loader aplica via funções do motor.

Diretriz anti-alucinação: todo texto vem destas linhas; o que o parser não
reconhece com confiança vai para a fila de revisão, nunca é inferido.
"""
from __future__ import annotations

import re
from datetime import date

from ..schemas.legislacao import (
    AgrupamentoCanonico,
    DispositivoCanonico,
    EventoHistorico,
    ItemRevisao,
    NormaCanonica,
)
from ..utils.id_factory import (
    canon_alinea,
    canon_artigo,
    canon_inciso,
    canon_item,
    canon_paragrafo,
    canon_subitem,
    ordem_sequencial,
    urn_lexml,
)
from .history_patterns import (
    INCLUIDO_RE,
    NAO_INTERPRETAR_RE,
    REDACAO_DADA_RE,
    REVOGADO_RE,
    resolve_norma_ref,
)

# ── Padrões de reconhecimento (spec §4, Etapa 1 — LC 95/1998, art. 10) ──────
ARTIGO_LINHA_RE = re.compile(r"^Art\.\s*(\d+)\s*(?:º|°)?\s*(-[A-Z])?\s*\.?\s*(.*)$")
PARAGRAFO_LINHA_RE = re.compile(r"^§\s*(\d+)\s*(?:º|°)?\s*\.?\s*(.*)$")
PARAGRAFO_UNICO_LINHA_RE = re.compile(r"^Parágrafo\s+[Úú]nico\s*[.:]?\s*(.*)$")
INCISO_LINHA_RE = re.compile(r"^([IVXLCDM]+)(-[A-Z])?\s*[-–—]\s*(.*)$")
ALINEA_LINHA_RE = re.compile(r"^([a-z])\)\s*(.*)$")
ITEM_LINHA_RE = re.compile(r"^(\d+)\.\s+(.*)$")
SUBITEM_LINHA_RE = re.compile(r"^(\d+\.\d+)\.?\s+(.*)$")
AGRUPAMENTO_LINHA_RE = re.compile(
    r"^(PARTE|LIVRO|T[ÍI]TULO|CAP[ÍI]TULO|Seç[ãa]o|Subseç[ãa]o)\s+([IVXLCDM]+|ÚNICO|ÚNICA)\s*(.*)$",
    re.IGNORECASE,
)

_TIPO_AGRUPAMENTO = {
    "parte": "parte", "livro": "livro", "título": "titulo", "titulo": "titulo",
    "capítulo": "capitulo", "capitulo": "capitulo",
    "seção": "secao", "secao": "secao", "subseção": "subsecao", "subsecao": "subsecao",
}
_NIVEL_DISPOSITIVO = {
    "artigo": 0, "paragrafo": 1, "inciso": 2, "alinea": 3, "item": 4, "subitem": 5,
}


def _clean_text(text: str) -> str:
    text = text.strip()
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    text = re.sub(r"\s+", " ", text)
    return text


def build_canonical_tree(
    doc_id: str,
    markdown_text: str,
    doc_meta: dict,
    corpus_index: dict[tuple, dict] | None = None,
) -> NormaCanonica:
    """Monta a árvore canônica de uma norma a partir do markdown parseado.

    ``doc_meta`` é a entrada do documento no manifest do corpus-scanner
    (authority, type, number, year, dataPublicacao...). ``corpus_index``
    (de history_patterns.build_corpus_index) resolve normas alteradoras.
    """
    corpus_index = corpus_index or {}
    numero = str(doc_meta.get("number")) if doc_meta.get("number") else None
    ano = int(doc_meta.get("year") or 0)
    autoridade = doc_meta.get("authority") or "federal"
    tipo_norma = doc_meta.get("type") or "lei_ordinaria"
    data_pub = date.fromisoformat(
        doc_meta.get("dataPublicacao") or doc_meta.get("dataVigor") or f"{ano}-01-01"
    )

    norma = NormaCanonica(
        doc_id=doc_id,
        tipo=tipo_norma,
        numero=numero,
        ano=ano,
        apelido=doc_id,
        urn_lexml=urn_lexml(autoridade, tipo_norma, ano, numero, doc_id),
        data_publicacao=data_pub,
        orgao_emissor=autoridade,
        ementa=doc_meta.get("description"),
        url_fonte_oficial=doc_meta.get("urlFonteOficial"),
        review_required=numero is None,
    )

    # Pilhas de contexto
    pilha: list[DispositivoCanonico] = []  # dispositivos abertos (artigo→...→subitem)
    agrup_pilha: list[tuple[int, AgrupamentoCanonico]] = []  # (nível, agrupamento)
    textos: dict[int, list[str]] = {}  # id(disp) → fragmentos de texto
    agrup_ordens: dict[str, int] = {}
    aguardando_nome_agrup: AgrupamentoCanonico | None = None
    nivel_agrup_ordem = ["parte", "livro", "titulo", "capitulo", "secao", "subsecao"]

    def _fechar_ate(nivel: int) -> None:
        while pilha and _NIVEL_DISPOSITIVO[pilha[-1].tipo] >= nivel:
            pilha.pop()

    def _abrir(disp: DispositivoCanonico, nivel: int, texto_inicial: str) -> None:
        _fechar_ate(nivel)
        if nivel == 0:
            norma.dispositivos.append(disp)
            if agrup_pilha:
                agrup_pilha[-1][1].artigos.append(disp.id_canonico)
        else:
            if not pilha:
                norma.review_queue.append(ItemRevisao(
                    doc_id=doc_id, trecho=disp.rotulo,
                    motivo="orfao_sem_pai", id_canonico=disp.id_canonico,
                ))
                return
            pilha[-1].filhos.append(disp)
        pilha.append(disp)
        textos[id(disp)] = [texto_inicial] if texto_inicial else []

    for num_linha, linha_bruta in enumerate(markdown_text.splitlines(), start=1):
        linha = linha_bruta.strip()
        if not linha:
            continue

        # Nome do agrupamento na(s) linha(s) seguinte(s) ao cabeçalho
        if aguardando_nome_agrup is not None:
            if not _qualquer_estrutura(linha):
                aguardando_nome_agrup.nome = _clean_text(linha)
                aguardando_nome_agrup = None
                continue
            aguardando_nome_agrup = None

        m = AGRUPAMENTO_LINHA_RE.match(linha)
        if m:
            tipo_ag = _TIPO_AGRUPAMENTO[m.group(1).lower()]
            nivel_ag = nivel_agrup_ordem.index(tipo_ag)
            agrup_ordens[tipo_ag] = agrup_ordens.get(tipo_ag, 0) + 1
            agrup = AgrupamentoCanonico(
                tipo=tipo_ag,
                rotulo=_clean_text(f"{m.group(1)} {m.group(2)}"),
                nome=_clean_text(m.group(3)) or None,
                ordem_sequencial=str(agrup_ordens[tipo_ag]),
            )
            while agrup_pilha and agrup_pilha[-1][0] >= nivel_ag:
                agrup_pilha.pop()
            if agrup_pilha:
                agrup_pilha[-1][1].filhos.append(agrup)
            else:
                norma.agrupamentos.append(agrup)
            agrup_pilha.append((nivel_ag, agrup))
            if agrup.nome is None:
                aguardando_nome_agrup = agrup
            pilha.clear()  # agrupamento fecha o artigo corrente
            continue

        m = ARTIGO_LINHA_RE.match(linha)
        if m:
            numero_art = m.group(1) + (m.group(2) or "")
            ordinal = int(m.group(1)) <= 9
            rotulo = f"Art. {numero_art}{'º' if ordinal else '.'}"
            disp = DispositivoCanonico(
                id_canonico=canon_artigo(numero_art),
                tipo="artigo",
                rotulo=rotulo,
                numero=numero_art,
                ordem_sequencial=str(ordem_sequencial(numero_art)),
            )
            _abrir(disp, 0, m.group(3))
            continue

        m = PARAGRAFO_UNICO_LINHA_RE.match(linha)
        if m and pilha:
            artigo = pilha[0]
            disp = DispositivoCanonico(
                id_canonico=canon_paragrafo(artigo.id_canonico, "un"),
                tipo="paragrafo",
                rotulo="Parágrafo único.",
                numero="un",
                ordem_sequencial=str(ordem_sequencial("un")),
            )
            _abrir(disp, 1, m.group(1))
            continue

        m = PARAGRAFO_LINHA_RE.match(linha)
        if m and pilha:
            artigo = pilha[0]
            numero_par = m.group(1)
            disp = DispositivoCanonico(
                id_canonico=canon_paragrafo(artigo.id_canonico, numero_par),
                tipo="paragrafo",
                rotulo=f"§ {numero_par}º" if int(numero_par) <= 9 else f"§ {numero_par}.",
                numero=numero_par,
                ordem_sequencial=str(ordem_sequencial(numero_par)),
            )
            _abrir(disp, 1, m.group(2))
            continue

        m = INCISO_LINHA_RE.match(linha)
        if m and pilha:
            _fechar_ate(2)
            pai = pilha[-1]  # último parágrafo aberto, senão o artigo
            numeral = m.group(1) + (m.group(2) or "")
            try:
                disp = DispositivoCanonico(
                    id_canonico=canon_inciso(pai.id_canonico, numeral),
                    tipo="inciso",
                    rotulo=numeral,
                    numero=numeral,
                    ordem_sequencial=str(ordem_sequencial(numeral)),
                )
            except ValueError:
                norma.review_queue.append(ItemRevisao(
                    doc_id=doc_id, trecho=linha[:120], motivo="parse", linha=num_linha,
                ))
                continue
            _abrir(disp, 2, m.group(3))
            continue

        m = ALINEA_LINHA_RE.match(linha)
        if m and pilha and pilha[-1].tipo in ("inciso", "alinea", "item", "subitem"):
            _fechar_ate(3)
            pai = pilha[-1]
            letra = m.group(1)
            disp = DispositivoCanonico(
                id_canonico=canon_alinea(pai.id_canonico, letra),
                tipo="alinea",
                rotulo=f"{letra})",
                numero=letra,
                ordem_sequencial=str(ordem_sequencial(str(ord(letra) - ord("a") + 1))),
            )
            _abrir(disp, 3, m.group(2))
            continue

        # Subitem (1.1) antes de item (1.) — só em contexto de item/subitem
        m = SUBITEM_LINHA_RE.match(linha)
        if m and pilha and pilha[-1].tipo in ("item", "subitem"):
            _fechar_ate(5)
            pai = pilha[-1]
            disp = DispositivoCanonico(
                id_canonico=canon_subitem(pai.id_canonico, m.group(1)),
                tipo="subitem",
                rotulo=f"{m.group(1)}.",
                numero=m.group(1),
                ordem_sequencial=str(ordem_sequencial(m.group(1))),
            )
            _abrir(disp, 5, m.group(2))
            continue

        # Item (1.) — apenas quando o contexto está em alínea (spec: evita falso positivo)
        m = ITEM_LINHA_RE.match(linha)
        if m and pilha and pilha[-1].tipo in ("alinea", "item"):
            _fechar_ate(4)
            pai = pilha[-1]
            disp = DispositivoCanonico(
                id_canonico=canon_item(pai.id_canonico, m.group(1)),
                tipo="item",
                rotulo=f"{m.group(1)}.",
                numero=m.group(1),
                ordem_sequencial=str(ordem_sequencial(m.group(1))),
            )
            _abrir(disp, 4, m.group(2))
            continue

        # Linha de continuação do dispositivo aberto
        if pilha:
            textos[id(pilha[-1])].append(linha)

    # Consolida textos e extrai histórico de cada dispositivo
    data_pub_norma = norma.data_publicacao
    for disp, _pai in _walk(norma):
        bruto = _clean_text(" ".join(textos.get(id(disp), [])))
        bruto = _extrair_historico(norma, disp, bruto, corpus_index, data_pub_norma)
        disp.texto_original = bruto or None
        if disp.texto_original is None and not disp.historico:
            disp.review_required = True
            disp.review_notes = "dispositivo sem texto extraído"
            norma.review_queue.append(ItemRevisao(
                doc_id=norma.doc_id, trecho=disp.rotulo,
                motivo="sem_texto", id_canonico=disp.id_canonico,
            ))

    return norma


def _qualquer_estrutura(linha: str) -> bool:
    return any(
        rx.match(linha)
        for rx in (
            ARTIGO_LINHA_RE, PARAGRAFO_LINHA_RE, PARAGRAFO_UNICO_LINHA_RE,
            INCISO_LINHA_RE, ALINEA_LINHA_RE, AGRUPAMENTO_LINHA_RE,
        )
    )


def _walk(norma: NormaCanonica):
    def _w(d: DispositivoCanonico, pai):
        yield d, pai
        for f in d.filhos:
            yield from _w(f, d)

    for art in norma.dispositivos:
        yield from _w(art, None)


def _extrair_historico(
    norma: NormaCanonica,
    disp: DispositivoCanonico,
    texto: str,
    corpus_index: dict[tuple, dict],
    data_pub_norma: date,
) -> str:
    """Converte anotações inline em EventoHistorico e as remove do texto.

    Sem o tachado do Planalto (perdido na conversão de PDF), a redação
    anterior a uma anotação "(Redação dada pela...)" é desconhecida — o
    dispositivo é tratado como introduzido pela alteradora na data dela e
    marcado para revisão (anti-alucinação: nunca inventar a redação original).
    """
    for m in NAO_INTERPRETAR_RE.finditer(texto):
        norma.review_queue.append(ItemRevisao(
            doc_id=norma.doc_id, trecho=m.group(0)[:120],
            motivo="nao_interpretar", id_canonico=disp.id_canonico,
        ))
        disp.review_required = True
    texto = NAO_INTERPRETAR_RE.sub("", texto)

    def _evento(m: re.Match, evento: str) -> None:
        ref_text = m.group(1)
        doc = resolve_norma_ref(ref_text, corpus_index)
        data_efeito = None
        if doc:
            raw = doc.get("dataVigor") or doc.get("dataPublicacao")
            data_efeito = date.fromisoformat(raw) if raw else None
        confiavel = doc is not None and data_efeito is not None
        if not confiavel:
            disp.review_required = True
            norma.review_queue.append(ItemRevisao(
                doc_id=norma.doc_id, trecho=m.group(0)[:120],
                motivo="ref_nao_resolvida", id_canonico=disp.id_canonico,
            ))
        disp.historico.append(EventoHistorico(
            evento=evento,
            norma_alteradora_ref=ref_text,
            norma_alteradora_doc_id=doc.get("documentId") if doc else None,
            data_efeito=data_efeito,
            texto=None if evento == "revogacao" else _clean_text(
                REDACAO_DADA_RE.sub("", INCLUIDO_RE.sub("", REVOGADO_RE.sub("", texto)))
            ) or None,
            confiavel=confiavel,
        ))

    for m in REDACAO_DADA_RE.finditer(texto):
        _evento(m, "alteracao")
        disp.review_notes = "redação original desconhecida (sem tachado na fonte PDF)"
    for m in INCLUIDO_RE.finditer(texto):
        _evento(m, "redacao_original")
    for m in REVOGADO_RE.finditer(texto):
        _evento(m, "revogacao")

    texto = REDACAO_DADA_RE.sub("", texto)
    texto = INCLUIDO_RE.sub("", texto)
    texto = REVOGADO_RE.sub("", texto)
    if disp.historico:
        # texto visível pertence ao último evento; identidade fica sem "original"
        return ""
    return _clean_text(texto)
