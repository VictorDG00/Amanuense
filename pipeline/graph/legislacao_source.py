"""Leitura da Base de Legislação Estruturada para montar o grafo.

Quando LEGISLACAO_DATABASE_URL está definida, a base é a fonte da verdade
das leis: status de vigência, datas, textos e relações normativas dos nós
normativos vêm daqui (vw_dispositivo_vigente / dispositivo_versao /
relacao_normativa), não dos JSONs intermediários.
"""
from __future__ import annotations

from datetime import date

from ..schemas import EDGE_DEFAULT_WEIGHTS, EdgeType, VigencyStatus
from ..utils.id_factory import disp_node_id, edge_id, norma_id

# tipo_relacao da base → EdgeType do grafo
_EDGE_POR_RELACAO: dict[str, EdgeType] = {
    "revoga": EdgeType.REVOGA_EXPRESSAMENTE,
    "altera": EdgeType.ALTERA,
    "acrescenta": EdgeType.ALTERA,
    "suspende": EdgeType.SUSPENDE,
    "regulamenta": EdgeType.REGULAMENTA,
    "remete": EdgeType.REMETE_A,
}


def _doc_por_norma(conn, doc_map: dict[str, int]) -> dict[int, str]:
    return {norma_pk: doc_id for doc_id, norma_pk in doc_map.items()}


def fetch_dispositivo_status(
    conn, doc_map: dict[str, int], data: date | None = None
) -> dict[str, dict]:
    """Estado de cada dispositivo na data (default hoje), por id de nó do grafo.

    Retorna {node_id: {status, texto, dataInicio, dataFim, numeroVersao,
    idCanonico, tipo, rotulo}}. Dispositivos sem redação vigente na data são
    'revogado' (evento revogacao) — a consulta temporal é uniforme.
    """
    data = data or date.today()
    por_norma = _doc_por_norma(conn, doc_map)
    if not por_norma:
        return {}
    rows = conn.execute(
        """
        SELECT d.id_norma, d.id_canonico, d.tipo, d.numero_rotulo,
               dv.evento, dv.texto, dv.data_inicio_vigencia, dv.data_fim_vigencia,
               dv.numero_versao
        FROM dispositivo d
        LEFT JOIN dispositivo_versao dv
               ON dv.id_dispositivo = d.id_dispositivo
              AND daterange(dv.data_inicio_vigencia, dv.data_fim_vigencia, '[)') @> %s
        WHERE d.id_norma = ANY(%s)
        """,
        (data, list(por_norma.keys())),
    ).fetchall()

    result: dict[str, dict] = {}
    for (norma_pk, id_canonico, tipo, rotulo, evento, texto,
         inicio, fim, numero_versao) in rows:
        doc_id = por_norma[norma_pk]
        if evento is None:
            status = None  # inexistente na data (ex.: acrescentado depois)
        elif evento == "revogacao":
            status = VigencyStatus.REVOGADO
        elif evento == "alteracao":
            status = VigencyStatus.ALTERADO
        else:
            status = VigencyStatus.VIGENTE
        result[disp_node_id(doc_id, id_canonico)] = {
            "status": status,
            "texto": texto,
            "dataInicio": inicio,
            "dataFim": fim,
            "numeroVersao": numero_versao,
            "idCanonico": id_canonico,
            "tipo": tipo,
            "rotulo": rotulo,
            "docId": doc_id,
        }
    return result


def fetch_norma_status(conn, doc_map: dict[str, int]) -> dict[str, dict]:
    """Status/datas de cada norma, por id de nó ('norma:{doc_id}')."""
    por_norma = _doc_por_norma(conn, doc_map)
    if not por_norma:
        return {}
    rows = conn.execute(
        "SELECT id_norma, status, data_publicacao, data_vigencia_inicio, "
        "data_vigencia_fim FROM norma WHERE id_norma = ANY(%s)",
        (list(por_norma.keys()),),
    ).fetchall()
    result: dict[str, dict] = {}
    for norma_pk, status, data_pub, vig_inicio, vig_fim in rows:
        result[norma_id(por_norma[norma_pk])] = {
            "status": VigencyStatus(status),
            "dataInicio": vig_inicio or data_pub,
            "dataFim": vig_fim,
        }
    return result


def fetch_relacao_edges(conn, doc_map: dict[str, int]) -> list[dict]:
    """relacao_normativa → arestas do grafo (dicts validáveis por GraphEdge)."""
    por_norma = _doc_por_norma(conn, doc_map)
    if not por_norma:
        return []
    rows = conn.execute(
        """
        SELECT r.tipo_relacao, r.data_efeito, r.observacao,
               r.id_norma_origem, o.id_canonico,
               r.id_norma_destino, d.id_canonico
        FROM relacao_normativa r
        LEFT JOIN dispositivo o ON o.id_dispositivo = r.id_dispositivo_origem
        LEFT JOIN dispositivo d ON d.id_dispositivo = r.id_dispositivo_destino
        WHERE r.id_norma_destino = ANY(%s)
        """,
        (list(por_norma.keys()),),
    ).fetchall()

    edges: list[dict] = []
    for (tipo_rel, data_efeito, observacao,
         norma_origem, canon_origem, norma_destino, canon_destino) in rows:
        etype = _EDGE_POR_RELACAO.get(tipo_rel)
        if etype is None or norma_origem not in por_norma or norma_destino not in por_norma:
            continue
        doc_origem = por_norma[norma_origem]
        doc_destino = por_norma[norma_destino]
        source = (
            disp_node_id(doc_origem, canon_origem) if canon_origem
            else norma_id(doc_origem)
        )
        target = (
            disp_node_id(doc_destino, canon_destino) if canon_destino
            else norma_id(doc_destino)
        )
        if source == target:
            continue
        edges.append({
            "id": edge_id(source, etype.value, target),
            "source": source,
            "target": target,
            "type": etype.value,
            "weight": EDGE_DEFAULT_WEIGHTS[etype],
            "direction": "forward",
            "implicit": False,
            "textEvidence": observacao,
            "dataEfeito": data_efeito.isoformat() if data_efeito else None,
            "review_required": False,
            "description": f"relacao_normativa: {tipo_rel}",
        })
    return edges


def fetch_versoes(conn, doc_map: dict[str, int]) -> dict[str, dict[str, dict]]:
    """Histórico real de versões por nó: {node_id: {'v1': {...}, 'v2': {...}}}."""
    por_norma = _doc_por_norma(conn, doc_map)
    if not por_norma:
        return {}
    rows = conn.execute(
        """
        SELECT d.id_norma, d.id_canonico, dv.numero_versao, dv.evento, dv.texto,
               dv.data_inicio_vigencia, dv.data_fim_vigencia,
               alt.tipo || ' ' || alt.numero || '/' || alt.ano
        FROM dispositivo d
        JOIN dispositivo_versao dv ON dv.id_dispositivo = d.id_dispositivo
        LEFT JOIN norma alt ON alt.id_norma = dv.norma_alteradora_id
        WHERE d.id_norma = ANY(%s)
        ORDER BY d.id_norma, d.id_canonico, dv.numero_versao
        """,
        (list(por_norma.keys()),),
    ).fetchall()

    versoes: dict[str, dict[str, dict]] = {}
    for (norma_pk, id_canonico, numero_versao, evento, texto,
         inicio, fim, alteradora) in rows:
        node = disp_node_id(por_norma[norma_pk], id_canonico)
        versoes.setdefault(node, {})[f"v{numero_versao}"] = {
            "vigencia": f"[{inicio},{fim or ''})",
            "evento": evento,
            "textoCompleto": texto or "(Revogado)",
            "nota": f"Redação dada por {alteradora}" if alteradora else "Redação original",
        }
    return versoes


def fetch_diff_entries(conn, doc_map: dict[str, int]) -> list[dict]:
    """Eventos de versão (≠ redação original) → entradas do diff-log."""
    por_norma = _doc_por_norma(conn, doc_map)
    if not por_norma:
        return []
    rows = conn.execute(
        """
        SELECT d.id_norma, d.id_canonico, dv.evento, dv.data_inicio_vigencia,
               dv.norma_alteradora_id
        FROM dispositivo d
        JOIN dispositivo_versao dv ON dv.id_dispositivo = d.id_dispositivo
        WHERE d.id_norma = ANY(%s) AND dv.evento <> 'redacao_original'
        ORDER BY dv.data_inicio_vigencia
        """,
        (list(por_norma.keys()),),
    ).fetchall()
    tipo_map = {"alteracao": "alter", "revogacao": "revoke", "renumeracao": "modify"}
    entries: list[dict] = []
    for norma_pk, id_canonico, evento, data_inicio, alteradora_pk in rows:
        doc_id = por_norma[norma_pk]
        node = disp_node_id(doc_id, id_canonico)
        origem = por_norma.get(alteradora_pk)
        entries.append({
            "data": data_inicio.isoformat(),
            "normaOrigem": norma_id(origem) if origem else "",
            "tipo": tipo_map.get(evento, "modify"),
            "dispositivo": node,
            "descricao": f"{evento} de {id_canonico} ({doc_id})",
            "impacto": "alto" if evento == "revogacao" else "medio",
            "nosAfetados": [node],
        })
    return entries
