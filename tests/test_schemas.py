import pytest
from datetime import date
from pipeline.schemas import (
    GraphNode, NodeType, VigenciaMeta, VigencyStatus,
    GraphEdge, EdgeType, EDGE_DEFAULT_WEIGHTS,
)


def make_vigencia(
    status: VigencyStatus = VigencyStatus.VIGENTE,
    data_fim: date | None = None,
) -> VigenciaMeta:
    return VigenciaMeta(
        dataInicio=date(2020, 11, 16),
        dataFim=data_fim,
        status=status,
        ultimaVerificacao=date(2026, 6, 1),
    )


# ── Node tests ──────────────────────────────────────────────────────────────


def test_normative_node_requires_vigencia():
    with pytest.raises(Exception):
        GraphNode(
            id="artigo:res-001:art-1",
            type=NodeType.ARTIGO,
            name="Art. 1º",
            summary="Test article",
        )


def test_normative_node_accepts_vigencia():
    node = GraphNode(
        id="artigo:res-001:art-1",
        type=NodeType.ARTIGO,
        name="Art. 1º",
        summary="Test article",
        vigenciaMeta=make_vigencia(),
    )
    assert node.type == NodeType.ARTIGO
    assert node.vigenciaMeta is not None


def test_non_normative_node_no_vigencia_required():
    node = GraphNode(
        id="papel:psp-direto",
        type=NodeType.PAPEL,
        name="PSP Direto",
        summary="Participante direto do Pix",
    )
    assert node.vigenciaMeta is None


def test_all_normative_types_require_vigencia():
    from pipeline.schemas import NORMATIVE_TYPES
    for node_type in NORMATIVE_TYPES:
        with pytest.raises(Exception, match="vigenciaMeta"):
            GraphNode(
                id=f"{node_type.value}:test",
                type=node_type,
                name="Test",
                summary="Test",
            )


def test_vigencia_invalid_dates():
    with pytest.raises(Exception):
        VigenciaMeta(
            dataInicio=date(2022, 1, 1),
            dataFim=date(2020, 1, 1),
            status=VigencyStatus.REVOGADO,
            ultimaVerificacao=date(2026, 6, 1),
        )


def test_vigencia_valid_null_fim():
    v = VigenciaMeta(
        dataInicio=date(2020, 1, 1),
        dataFim=None,
        status=VigencyStatus.VIGENTE,
        ultimaVerificacao=date(2026, 6, 1),
    )
    assert v.dataFim is None


def test_vigencia_revogado_with_fim():
    v = VigenciaMeta(
        dataInicio=date(2020, 1, 1),
        dataFim=date(2023, 6, 1),
        status=VigencyStatus.REVOGADO,
        ultimaVerificacao=date(2026, 6, 1),
    )
    assert v.status == VigencyStatus.REVOGADO


# ── Edge tests ──────────────────────────────────────────────────────────────


def test_edge_no_self_reference():
    with pytest.raises(Exception):
        GraphEdge(
            id="x--obriga--x",
            source="artigo:res-001:art-1",
            target="artigo:res-001:art-1",
            type=EdgeType.OBRIGA,
            weight=0.9,
        )


def test_edge_implicit_requires_confidence():
    with pytest.raises(Exception):
        GraphEdge(
            id="a--remete_a--b",
            source="artigo:res-001:art-1",
            target="artigo:res-001:art-2",
            type=EdgeType.REMETE_A,
            weight=0.7,
            implicit=True,
        )


def test_edge_implicit_with_confidence_ok():
    edge = GraphEdge(
        id="a--remete_a--b",
        source="artigo:res-001:art-1",
        target="artigo:res-001:art-2",
        type=EdgeType.REMETE_A,
        weight=0.7,
        implicit=True,
        confidence=0.85,
    )
    assert edge.implicit is True
    assert edge.confidence == 0.85


def test_all_edge_types_have_weights():
    for et in EdgeType:
        assert et in EDGE_DEFAULT_WEIGHTS, f"Missing weight for EdgeType.{et.name}"


def test_edge_default_weights_range():
    for et, weight in EDGE_DEFAULT_WEIGHTS.items():
        assert 0.0 <= weight <= 1.0, f"Weight out of range for {et.name}: {weight}"
