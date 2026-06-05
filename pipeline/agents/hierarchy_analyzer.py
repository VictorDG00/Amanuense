from __future__ import annotations
import re
from datetime import datetime
from pathlib import Path
from .base import BaseAgent, console
from ..parsers.bcb_patterns import CROSS_REF_RE, REGULAMENTA_RE
from ..schemas import EdgeType, EDGE_DEFAULT_WEIGHTS, NormativeLayer, LAYER_LEVELS
from ..utils.id_factory import norma_id, artigo_id, edge_id

# Mapping corpus doc types to normative layer
_TYPE_LAYER: dict[str, NormativeLayer] = {
    "resolucao": NormativeLayer.RESOLUCAO,
    "circular": NormativeLayer.CIRCULAR,
    "instrucao_normativa": NormativeLayer.INSTRUCAO_NORMATIVA,
    "lei_complementar": NormativeLayer.LEI_COMPLEMENTAR,
    "lei_ordinaria": NormativeLayer.LEI_ORDINARIA,
    "manual": NormativeLayer.MANUAL,
}

# Map doc_id fragments to canonical doc ID for cross-reference resolution
def _build_doc_lookup(documents: list[dict]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for doc in documents:
        doc_id = doc["documentId"]
        lookup[doc_id] = doc_id
        num = str(doc.get("number", "") or "")
        year = str(doc.get("year", "") or "")
        dtype = doc.get("type", "").lower()
        if num and year:
            lookup[f"{num}/{year}"] = doc_id
            lookup[f"{num}.{year}"] = doc_id
        if num:
            lookup[num] = doc_id
        # e.g. "3952" matches circular-bcb-3952-2019
        if dtype and num:
            lookup[f"{dtype}-{num}"] = doc_id
    return lookup


class HierarchyAnalyzerAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__("hierarchy-analyzer")

    def run(self, intermediate_dir: Path, corpus_dir: Path) -> None:
        manifest_path = intermediate_dir / "corpus_scanner.json"
        if not manifest_path.exists():
            manifest_path = intermediate_dir / "scan_manifest.json"
        norm_path = intermediate_dir / "norm_analyzer.json"

        if not manifest_path.exists() or not norm_path.exists():
            console.print("[red]ERROR:[/red] scan_manifest and norm_analyzer outputs required")
            return

        manifest = self._load_json(manifest_path)
        norm_data = self._load_json(norm_path)
        documents = manifest.get("documents", [])
        doc_lookup = _build_doc_lookup(documents)

        edges: list[dict] = []
        layers_map: dict[str, list[str]] = {}

        # Build lookup: node_id -> doc_id
        node_to_doc: dict[str, str] = {}
        for doc_id, doc_info in norm_data.get("byDocument", {}).items():
            for node in doc_info.get("nodes", []):
                node_to_doc[node["id"]] = doc_id

        # Populate layers from norm nodes
        for doc_id, doc_info in norm_data.get("byDocument", {}).items():
            for node in doc_info.get("nodes", []):
                layer_val = node.get("normativeLayer")
                if layer_val:
                    layers_map.setdefault(layer_val, []).append(node["id"])

        # Find REGULAMENTA relationships: circular → resolucao
        doc_type_map = {d["documentId"]: d.get("type", "").lower() for d in documents}
        doc_meta_map = {d["documentId"]: d for d in documents}

        for doc in documents:
            doc_id = doc["documentId"]
            dtype = doc.get("type", "").lower()
            parsed_path = Path(corpus_dir.parent) / doc.get("parsedPath", "")
            if not parsed_path.exists():
                continue

            text = parsed_path.read_text(encoding="utf-8")

            # Check if this norm "regulamenta" another
            if REGULAMENTA_RE.search(text):
                # Infer: circular/IN regulamenta resolução/lei
                for other_doc in documents:
                    other_id = other_doc["documentId"]
                    other_type = other_doc.get("type", "").lower()
                    if other_id == doc_id:
                        continue
                    src_level = LAYER_LEVELS.get(_TYPE_LAYER.get(dtype, NormativeLayer.MANUAL), 99)
                    tgt_level = LAYER_LEVELS.get(_TYPE_LAYER.get(other_type, NormativeLayer.MANUAL), 99)
                    if src_level > tgt_level:
                        # source is subordinate to target
                        eid = edge_id(norma_id(doc_id), EdgeType.REGULAMENTA.value, norma_id(other_id))
                        edges.append({
                            "id": eid,
                            "source": norma_id(doc_id),
                            "target": norma_id(other_id),
                            "type": EdgeType.REGULAMENTA.value,
                            "weight": EDGE_DEFAULT_WEIGHTS[EdgeType.REGULAMENTA],
                            "direction": "forward",
                            "implicit": False,
                            "review_required": True,
                            "description": f"{doc_id} regulamenta {other_id}",
                        })
                        break

            # SUBORDINA_SE_A: circular subordina-se à resolução (hierarchy)
            for other_doc in documents:
                other_id = other_doc["documentId"]
                if other_id == doc_id:
                    continue
                src_level = LAYER_LEVELS.get(_TYPE_LAYER.get(dtype, NormativeLayer.MANUAL), 99)
                tgt_type = other_doc.get("type", "").lower()
                tgt_level = LAYER_LEVELS.get(_TYPE_LAYER.get(tgt_type, NormativeLayer.MANUAL), 99)
                if src_level > tgt_level:
                    eid = edge_id(norma_id(doc_id), EdgeType.SUBORDINA_SE_A.value, norma_id(other_id))
                    if not any(e["id"] == eid for e in edges):
                        edges.append({
                            "id": eid,
                            "source": norma_id(doc_id),
                            "target": norma_id(other_id),
                            "type": EdgeType.SUBORDINA_SE_A.value,
                            "weight": EDGE_DEFAULT_WEIGHTS[EdgeType.SUBORDINA_SE_A],
                            "direction": "forward",
                            "implicit": False,
                            "review_required": False,
                            "description": f"{dtype} subordina-se a {tgt_type}",
                        })

            # REMETE_A: scan articles for cross-document references
            for match in CROSS_REF_RE.finditer(text):
                art_num = match.group(1)
                doc_ref = match.group(2)
                if not doc_ref or not art_num:
                    continue
                target_doc_id = doc_lookup.get(doc_ref)
                if not target_doc_id or target_doc_id == doc_id:
                    continue
                # find article node in target
                target_art_id = artigo_id(target_doc_id, art_num)
                # find source article by position in text
                art_before = text[: match.start()].rfind("Art.")
                src_art_text = text[art_before : art_before + 20] if art_before >= 0 else ""
                src_art_match = re.search(r"Art\.\s*(\d+(?:-[A-Z])?)", src_art_text)
                src_art_num = src_art_match.group(1) if src_art_match else "1"
                src_art_id = artigo_id(doc_id, src_art_num)

                eid = edge_id(src_art_id, EdgeType.REMETE_A.value, target_art_id)
                if not any(e["id"] == eid for e in edges):
                    edges.append({
                        "id": eid,
                        "source": src_art_id,
                        "target": target_art_id,
                        "type": EdgeType.REMETE_A.value,
                        "weight": EDGE_DEFAULT_WEIGHTS[EdgeType.REMETE_A],
                        "direction": "forward",
                        "implicit": False,
                        "review_required": False,
                        "textEvidence": match.group(0)[:200],
                    })

        # Build Layer objects
        layer_objects = []
        layer_info = {
            NormativeLayer.CF.value: (1, "Constituição Federal"),
            NormativeLayer.LEI_COMPLEMENTAR.value: (2, "Lei Complementar"),
            NormativeLayer.LEI_ORDINARIA.value: (2, "Lei Ordinária"),
            NormativeLayer.RESOLUCAO.value: (3, "Resolução BCB/CMN"),
            NormativeLayer.CIRCULAR.value: (4, "Circular BCB"),
            NormativeLayer.INSTRUCAO_NORMATIVA.value: (5, "Instrução Normativa"),
            NormativeLayer.MANUAL.value: (6, "Manual Operacional"),
        }
        for layer_val, node_ids in layers_map.items():
            level, name = layer_info.get(layer_val, (9, layer_val))
            layer_objects.append({
                "id": f"layer-{layer_val}",
                "name": name,
                "normativeLevel": level,
                "nodeIds": node_ids,
                "description": f"Nível {level} da hierarquia normativa: {name}",
            })
        layer_objects.sort(key=lambda x: x["normativeLevel"])

        output = {
            "generatedAt": datetime.now().isoformat(),
            "edges": edges,
            "layers": layer_objects,
        }
        self._save_json(intermediate_dir / "hierarchy_analyzer.json", output)
        console.print(f"[green]✓[/green] hierarchy-analyzer: {len(edges)} edges, {len(layer_objects)} layers")
