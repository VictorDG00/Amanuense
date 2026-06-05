from __future__ import annotations
from datetime import datetime, date
from ..schemas import (
    GraphNode, GraphEdge, KnowledgeGraph, VigencyStatus,
    VigencyIndex, VigencyIndexEntry, DiffLog, DiffLogEntry,
    REVOCATION_EDGE_TYPES,
)
from ..config import VIGENCY_REVIEW_STALENESS_DAYS


def apply_vigency_updates(
    nodes: list[GraphNode],
    updates: list[dict],
) -> list[GraphNode]:
    node_map = {n.id: n for n in nodes}
    for upd in updates:
        node_id = upd.get("nodeId", "")
        new_status_val = upd.get("newStatus", "")
        if node_id not in node_map or not new_status_val:
            continue
        try:
            new_status = VigencyStatus(new_status_val)
        except ValueError:
            continue
        node = node_map[node_id]
        if node.vigenciaMeta is not None:
            node.vigenciaMeta.status = new_status
            if new_status == VigencyStatus.REVOGADO:
                data_efeito = upd.get("dataEfeito")
                if data_efeito:
                    try:
                        node.vigenciaMeta.dataFim = date.fromisoformat(data_efeito)
                    except ValueError:
                        pass
    return list(node_map.values())


def propagate_revocation(graph: KnowledgeGraph) -> KnowledgeGraph:
    node_map = {n.id: n for n in graph.nodes}

    # Build child → parent map (ARTIGO/INCISO nodes grouped by sourceDocument)
    norma_children: dict[str, list[str]] = {}
    for node in graph.nodes:
        if node.sourceDocument and node.type.value in ("artigo", "inciso", "paragrafo"):
            parent_id = f"norma:{node.sourceDocument}"
            norma_children.setdefault(parent_id, []).append(node.id)

    # Find revoked nodes from edges
    for edge in graph.edges:
        if edge.type in REVOCATION_EDGE_TYPES:
            target = node_map.get(edge.target)
            if target and target.vigenciaMeta:
                if edge.type.value == "revoga_expressamente":
                    target.vigenciaMeta.status = VigencyStatus.REVOGADO
                    edge.stale = True
                elif edge.type.value == "suspende":
                    target.vigenciaMeta.status = VigencyStatus.SUSPENSO
                elif edge.type.value in ("altera", "revoga_parcialmente"):
                    target.vigenciaMeta.status = VigencyStatus.ALTERADO

    # Propagate REVOGADO from NORMA to its children
    for node in graph.nodes:
        if node.type.value == "norma" and node.vigenciaMeta:
            if node.vigenciaMeta.status == VigencyStatus.REVOGADO:
                for child_id in norma_children.get(node.id, []):
                    child = node_map.get(child_id)
                    if child and child.vigenciaMeta:
                        child.vigenciaMeta.status = VigencyStatus.REVOGADO

    # Mark edges deprecated/stale
    for edge in graph.edges:
        src = node_map.get(edge.source)
        tgt = node_map.get(edge.target)
        if src and src.vigenciaMeta and src.vigenciaMeta.status == VigencyStatus.REVOGADO:
            edge.deprecated = True
        if tgt and tgt.vigenciaMeta and tgt.vigenciaMeta.status == VigencyStatus.REVOGADO:
            edge.stale = True

    return graph


def build_vigency_index(graph: KnowledgeGraph, corpus: str) -> VigencyIndex:
    entries: list[VigencyIndexEntry] = []
    by_status: dict[str, int] = {}

    node_map = {n.id: n for n in graph.nodes}
    affected_edges: dict[str, list[str]] = {}
    for edge in graph.edges:
        if edge.type in REVOCATION_EDGE_TYPES:
            affected_edges.setdefault(edge.target, []).append(edge.id)

    for node in graph.nodes:
        if node.vigenciaMeta is None:
            continue
        status_key = node.vigenciaMeta.status.value
        by_status[status_key] = by_status.get(status_key, 0) + 1
        entries.append(VigencyIndexEntry(
            nodeId=node.id,
            normId=node.sourceDocument or node.id,
            status=node.vigenciaMeta.status,
            dataInicio=node.vigenciaMeta.dataInicio,
            dataFim=node.vigenciaMeta.dataFim,
            affectedByEdgeIds=affected_edges.get(node.id, []),
            ultimaVerificacao=node.vigenciaMeta.ultimaVerificacao,
        ))

    return VigencyIndex(
        generatedAt=datetime.now(),
        corpus=corpus,
        total=len(entries),
        byStatus=by_status,
        entries=entries,
    )


def build_diff_log(entries: list[dict]) -> DiffLog:
    log_entries: list[DiffLogEntry] = []
    for e in entries:
        try:
            ts_str = e.get("data", datetime.now().isoformat())
            if len(ts_str) == 10:
                ts_str += "T00:00:00"
            log_entries.append(DiffLogEntry(
                timestamp=datetime.fromisoformat(ts_str),
                changeType=e.get("tipo", "modify"),
                affectedNodeIds=e.get("nosAfetados", []),
                affectedEdgeIds=[],
                description=e.get("descricao", ""),
                corpusFile=e.get("normaOrigem", ""),
                impacto=e.get("impacto", "medio"),
            ))
        except Exception:
            continue
    log_entries.sort(key=lambda x: x.timestamp)
    return DiffLog(generatedAt=datetime.now(), entries=log_entries)


def find_stale_nodes(graph: KnowledgeGraph, staleness_days: int = VIGENCY_REVIEW_STALENESS_DAYS) -> list[str]:
    stale: list[str] = []
    today = date.today()
    for node in graph.nodes:
        if node.vigenciaMeta:
            delta = (today - node.vigenciaMeta.ultimaVerificacao).days
            if delta > staleness_days:
                stale.append(node.id)
    return stale
