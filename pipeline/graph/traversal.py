from __future__ import annotations
from collections import deque
import networkx as nx
from ..schemas import KnowledgeGraph, EdgeType

_HIERARCHY_EDGE_TYPES = {
    EdgeType.SUBORDINA_SE_A.value,
    EdgeType.REGULAMENTA.value,
}

_OBLIGATION_EDGE_TYPES = {
    EdgeType.OBRIGA.value,
    EdgeType.ATRIBUI_RESPONSABILIDADE.value,
    EdgeType.APLICA_A.value,
    EdgeType.PROIBE.value,
    EdgeType.PERMITE.value,
}


def build_nx_graph(graph: KnowledgeGraph) -> nx.DiGraph:
    G = nx.DiGraph()
    for node in graph.nodes:
        G.add_node(
            node.id,
            type=node.type.value,
            name=node.name,
            status=node.vigenciaMeta.status.value if node.vigenciaMeta else "vigente",
            layer=node.normativeLayer.value if node.normativeLayer else "",
        )
    for edge in graph.edges:
        if not edge.deprecated:
            G.add_edge(
                edge.source,
                edge.target,
                type=edge.type.value,
                weight=edge.weight,
                implicit=edge.implicit,
            )
    return G


def find_article_correlations(
    nx_graph: nx.DiGraph,
    source_id: str,
    max_depth: int = 2,
) -> list[tuple[str, str, int]]:
    if source_id not in nx_graph:
        return []
    results: list[tuple[str, str, int]] = []
    visited = {source_id}
    queue = deque([(source_id, 0)])
    while queue:
        current, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for neighbor in list(nx_graph.successors(current)) + list(nx_graph.predecessors(current)):
            if neighbor not in visited:
                visited.add(neighbor)
                edge_data = (
                    nx_graph.get_edge_data(current, neighbor)
                    or nx_graph.get_edge_data(neighbor, current)
                    or {}
                )
                results.append((neighbor, edge_data.get("type", ""), depth + 1))
                queue.append((neighbor, depth + 1))
    return results


def get_normative_ancestors(nx_graph: nx.DiGraph, node_id: str) -> list[str]:
    ancestors: list[str] = []
    visited = {node_id}
    queue = deque([node_id])
    while queue:
        current = queue.popleft()
        for successor in nx_graph.successors(current):
            edge_data = nx_graph.get_edge_data(current, successor) or {}
            if edge_data.get("type") in _HIERARCHY_EDGE_TYPES and successor not in visited:
                ancestors.append(successor)
                visited.add(successor)
                queue.append(successor)
    return ancestors


def get_role_obligations(
    nx_graph: nx.DiGraph,
    papel_id: str,
) -> list[tuple[str, str]]:
    obligations: list[tuple[str, str]] = []
    for predecessor in nx_graph.predecessors(papel_id):
        edge_data = nx_graph.get_edge_data(predecessor, papel_id) or {}
        etype = edge_data.get("type", "")
        if etype in _OBLIGATION_EDGE_TYPES:
            obligations.append((predecessor, etype))
    return obligations


def shortest_normative_path(nx_graph: nx.DiGraph, source: str, target: str) -> list[str]:
    try:
        return nx.shortest_path(nx_graph, source, target)
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return []


def cluster_by_topic(graph: KnowledgeGraph, tag: str) -> list[str]:
    return [n.id for n in graph.nodes if tag.lower() in [t.lower() for t in n.tags]]
