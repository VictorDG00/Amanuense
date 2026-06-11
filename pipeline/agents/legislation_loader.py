"""Agente legislation-loader — carga da árvore canônica no PostgreSQL.

Etapa 3 da spec: toda mutação passa pelas funções do motor de versionamento
(fn_criar_norma, fn_inserir_dispositivo, fn_registrar_alteracao,
fn_registrar_revogacao) — nunca INSERT direto nas tabelas de versão. A carga
é cronológica (normas por data de publicação; eventos por data de efeito) e
idempotente (skip por urn_lexml e por (id_norma, id_canonico)).

Sem LEGISLACAO_DATABASE_URL o agente apenas gera as árvores canônicas em
intermediate/<run>/canonical_tree/ (modo legado, com warning).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from rich.console import Console

from ..parsers.canonical_tree import build_canonical_tree
from ..parsers.history_patterns import build_corpus_index
from ..schemas.legislacao import (
    DispositivoCanonico,
    ItemRevisao,
    NormaCanonica,
    texto_vigente,
)
from .base import BaseAgent

console = Console()


class LegislationLoaderAgent(BaseAgent):
    def __init__(self) -> None:
        # Agente determinístico: não usa LLM (diretriz anti-alucinação) —
        # não instancia o ClaudeClient do BaseAgent.
        self.name = "legislation-loader"

    def run(self, intermediate_dir: Path, corpus_dir: Path) -> None:
        from db.legislacao import legislacao_enabled

        manifest_path = intermediate_dir / "corpus_scanner.json"
        if not manifest_path.exists():
            manifest_path = intermediate_dir / "scan_manifest.json"
        if not manifest_path.exists():
            console.print("[red]ERROR:[/red] scan_manifest.json not found — run corpus-scanner first")
            return

        manifest = self._load_json(manifest_path)
        documents = sorted(
            manifest.get("documents", []),
            key=lambda d: d.get("dataPublicacao") or "",
        )
        corpus_index = build_corpus_index(documents)

        # Etapa 1: árvores canônicas (sempre, mesmo sem DB)
        tree_dir = intermediate_dir / "canonical_tree"
        tree_dir.mkdir(parents=True, exist_ok=True)
        normas: list[NormaCanonica] = []
        review_queue: list[ItemRevisao] = []
        for doc in documents:
            doc_id = doc["documentId"]
            parsed_path = Path(corpus_dir).parent / doc["parsedPath"]
            if not parsed_path.exists():
                console.print(f"[yellow]⚠[/yellow] {doc_id}: parsed markdown ausente, pulando")
                continue
            norma = build_canonical_tree(
                doc_id, parsed_path.read_text(encoding="utf-8"), doc, corpus_index
            )
            self._save_json(tree_dir / f"{doc_id}.json", norma.model_dump(mode="json"))
            normas.append(norma)
            review_queue.extend(norma.review_queue)

        result: dict = {
            "normas": {},
            "loaded": 0,
            "skipped": 0,
            "eventos_aplicados": 0,
            "review_queue": [i.model_dump(mode="json") for i in review_queue],
            "validation": {},
            "dbEnabled": legislacao_enabled(),
        }

        # Etapa 2: carga no PostgreSQL
        if not legislacao_enabled():
            console.print(
                "[yellow]⚠[/yellow] LEGISLACAO_DATABASE_URL não definida — "
                "árvores geradas, carga pulada (modo legado)"
            )
            self._save_json(intermediate_dir / "legislation_loader.json", result)
            return

        from db.legislacao import get_conn, init_legislacao_db

        init_legislacao_db()
        with get_conn() as conn:
            doc_map = self._criar_normas(conn, normas, result)
            self._criar_agrupamentos(conn, normas, doc_map)
            self._criar_dispositivos(conn, normas, doc_map, result)
            self._aplicar_eventos(conn, normas, doc_map, result)
            self._validar_consolidado(conn, normas, doc_map, result)

        self._save_json(intermediate_dir / "legislation_loader.json", result)
        console.print(
            f"[green]✓[/green] carga: {result['loaded']} dispositivos novos, "
            f"{result['skipped']} já existentes, {result['eventos_aplicados']} eventos, "
            f"{len(result['review_queue'])} itens p/ revisão"
        )

    # ── Normas ───────────────────────────────────────────────────────────
    def _criar_normas(self, conn, normas: list[NormaCanonica], result: dict) -> dict[str, int]:
        doc_map: dict[str, int] = {}
        for n in normas:
            row = conn.execute(
                "SELECT id_norma FROM norma WHERE urn_lexml = %s", (n.urn_lexml,)
            ).fetchone()
            if row:
                doc_map[n.doc_id] = row[0]
            else:
                row = conn.execute(
                    "SELECT fn_criar_norma(%s,%s,%s::smallint,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        n.tipo, n.numero or n.doc_id, n.ano, n.data_publicacao,
                        n.ementa, None, n.apelido, n.esfera, n.orgao_emissor,
                        n.urn_lexml, n.url_fonte_oficial,
                    ),
                ).fetchone()
                doc_map[n.doc_id] = row[0]
            conn.commit()
            result["normas"][n.doc_id] = {"norma_id": doc_map[n.doc_id], "urn": n.urn_lexml}
        return doc_map

    # ── Agrupamentos (sem função no motor; INSERT idempotente) ──────────
    def _criar_agrupamentos(self, conn, normas: list[NormaCanonica], doc_map: dict) -> None:
        def _inserir(norma_id: int, agrup, id_pai: int | None) -> None:
            row = conn.execute(
                "SELECT id_agrupamento FROM agrupamento "
                "WHERE id_norma = %s AND tipo = %s AND numero_rotulo = %s",
                (norma_id, agrup.tipo, agrup.rotulo),
            ).fetchone()
            if row:
                ag_id = row[0]
            else:
                row = conn.execute(
                    "INSERT INTO agrupamento (id_norma, tipo, numero_rotulo, nome, "
                    "ordem_sequencial, id_pai) VALUES (%s,%s,%s,%s,%s,%s) "
                    "RETURNING id_agrupamento",
                    (norma_id, agrup.tipo, agrup.rotulo, agrup.nome,
                     Decimal(agrup.ordem_sequencial), id_pai),
                ).fetchone()
                ag_id = row[0]
            self._agrup_por_artigo.update({(norma_id, art): ag_id for art in agrup.artigos})
            for filho in agrup.filhos:
                _inserir(norma_id, filho, ag_id)

        self._agrup_por_artigo: dict[tuple[int, str], int] = {}
        for n in normas:
            for agrup in n.agrupamentos:
                _inserir(doc_map[n.doc_id], agrup, None)
            conn.commit()

    # ── Dispositivos (identidade + redação de criação) ───────────────────
    def _criar_dispositivos(
        self, conn, normas: list[NormaCanonica], doc_map: dict, result: dict
    ) -> None:
        for n in normas:
            norma_id = doc_map[n.doc_id]
            data_inicio = date.fromisoformat(str(n.data_publicacao))
            for disp, pai in _walk(n):
                criado = self._inserir_dispositivo(
                    conn, n, norma_id, disp, pai, data_inicio, doc_map, result
                )
                if criado:
                    result["loaded"] += 1
                else:
                    result["skipped"] += 1

    def _inserir_dispositivo(
        self, conn, n: NormaCanonica, norma_id: int,
        disp: DispositivoCanonico, pai: DispositivoCanonico | None,
        data_inicio: date, doc_map: dict, result: dict,
    ) -> bool:
        row = conn.execute(
            "SELECT id_dispositivo FROM dispositivo WHERE id_norma = %s AND id_canonico = %s",
            (norma_id, disp.id_canonico),
        ).fetchone()
        if row:
            return False

        id_pai = None
        if pai is not None:
            prow = conn.execute(
                "SELECT id_dispositivo FROM dispositivo WHERE id_norma = %s AND id_canonico = %s",
                (norma_id, pai.id_canonico),
            ).fetchone()
            if prow is None:
                result["review_queue"].append(ItemRevisao(
                    doc_id=n.doc_id, trecho=disp.rotulo, motivo="pai_ausente",
                    id_canonico=disp.id_canonico,
                ).model_dump(mode="json"))
                return False
            id_pai = prow[0]

        id_agrupamento = None
        if disp.tipo == "artigo":
            id_agrupamento = self._agrup_por_artigo.get((norma_id, disp.id_canonico))

        # Dispositivo sem redação original conhecida: criado pela alteradora
        # na data dela (anotação "Incluído"/"Redação dada" sem tachado).
        texto = disp.texto_original
        data_vigencia = data_inicio
        introdutora_id = None
        if texto is None and disp.historico:
            ev = disp.historico[0]
            if not ev.confiavel or ev.texto is None or ev.data_efeito is None:
                if ev.evento != "revogacao":
                    return False  # já está na fila de revisão
                # revogação anotada sem texto anterior: nada a criar com confiança
                result["review_queue"].append(ItemRevisao(
                    doc_id=n.doc_id, trecho=disp.rotulo,
                    motivo="revogado_sem_texto_anterior", id_canonico=disp.id_canonico,
                ).model_dump(mode="json"))
                return False
            texto = ev.texto
            data_vigencia = ev.data_efeito
            if ev.norma_alteradora_doc_id:
                introdutora_id = doc_map.get(ev.norma_alteradora_doc_id)
        if texto is None:
            return False  # sem texto confiável — fila já alimentada pelo parser

        try:
            conn.execute(
                "SELECT fn_inserir_dispositivo(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    norma_id, disp.tipo, disp.rotulo, disp.id_canonico, texto,
                    Decimal(disp.ordem_sequencial), data_vigencia,
                    id_pai, id_agrupamento, introdutora_id,
                ),
            )
            conn.commit()  # por dispositivo: falha posterior não desfaz anteriores
            return True
        except Exception as e:  # constraint/motor: rollback pontual + fila
            conn.rollback()
            result["review_queue"].append(ItemRevisao(
                doc_id=n.doc_id, trecho=str(e)[:200], motivo="erro_carga",
                id_canonico=disp.id_canonico,
            ).model_dump(mode="json"))
            return False

    # ── Eventos de histórico (cronológicos, globais) ─────────────────────
    def _aplicar_eventos(
        self, conn, normas: list[NormaCanonica], doc_map: dict, result: dict
    ) -> None:
        eventos = []
        for n in normas:
            for disp, _pai in _walk(n):
                inicio = 1 if (disp.texto_original is None and disp.historico) else 0
                for ev in disp.historico[inicio:]:
                    eventos.append((n, disp, ev))
        eventos.sort(key=lambda t: (t[2].data_efeito or date.max))

        for n, disp, ev in eventos:
            if not ev.confiavel or ev.data_efeito is None:
                continue  # fila já alimentada pelo parser
            norma_id = doc_map[n.doc_id]
            alteradora_id = doc_map.get(ev.norma_alteradora_doc_id or "")
            if alteradora_id is None:
                continue
            row = conn.execute(
                "SELECT id_dispositivo FROM dispositivo WHERE id_norma = %s AND id_canonico = %s",
                (norma_id, disp.id_canonico),
            ).fetchone()
            if row is None:
                continue
            disp_id = row[0]
            # Idempotência: evento da mesma alteradora na mesma data já aplicado?
            dup = conn.execute(
                "SELECT 1 FROM dispositivo_versao WHERE id_dispositivo = %s "
                "AND norma_alteradora_id = %s AND data_inicio_vigencia = %s",
                (disp_id, alteradora_id, ev.data_efeito),
            ).fetchone()
            if dup:
                continue
            try:
                if ev.evento == "revogacao":
                    conn.execute(
                        "SELECT fn_registrar_revogacao(%s,%s,%s)",
                        (disp_id, alteradora_id, ev.data_efeito),
                    )
                elif ev.evento == "alteracao" and ev.texto:
                    conn.execute(
                        "SELECT fn_registrar_alteracao(%s,%s,%s,%s)",
                        (disp_id, ev.texto, alteradora_id, ev.data_efeito),
                    )
                else:
                    continue
                conn.commit()
                result["eventos_aplicados"] += 1
            except Exception as e:
                conn.rollback()
                result["review_queue"].append(ItemRevisao(
                    doc_id=n.doc_id, trecho=str(e)[:200], motivo="erro_evento",
                    id_canonico=disp.id_canonico,
                ).model_dump(mode="json"))

    # ── Validação pós-carga (spec §4, Etapa 4) ───────────────────────────
    def _validar_consolidado(
        self, conn, normas: list[NormaCanonica], doc_map: dict, result: dict
    ) -> None:
        for n in normas:
            row = conn.execute(
                "SELECT fn_texto_consolidado(%s, %s)", (doc_map[n.doc_id], date.today())
            ).fetchone()
            consolidado_db = _normalizar(row[0] or "")
            esperado = _normalizar(_consolidado_da_arvore(n))
            ok = consolidado_db == esperado
            result["validation"][n.doc_id] = {
                "ok": ok,
                "chars_db": len(consolidado_db),
                "chars_arvore": len(esperado),
            }
            if not ok:
                result["review_queue"].append(ItemRevisao(
                    doc_id=n.doc_id,
                    trecho=f"db={len(consolidado_db)} chars, árvore={len(esperado)} chars",
                    motivo="diff_consolidado",
                ).model_dump(mode="json"))


def _walk(norma: NormaCanonica):
    def _w(d: DispositivoCanonico, pai):
        yield d, pai
        for f in d.filhos:
            yield from _w(f, d)

    for art in norma.dispositivos:
        yield from _w(art, None)


def _normalizar(texto: str) -> str:
    import re
    import unicodedata

    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", texto)).strip()


def _consolidado_da_arvore(norma: NormaCanonica, nivel: int = 0) -> str:
    """Replica o formato de fn_texto_consolidado a partir da árvore canônica."""
    linhas: list[str] = []

    def _emit(disp: DispositivoCanonico, nivel: int) -> None:
        texto = texto_vigente(disp)
        if texto is None:
            return  # dispositivo sem texto confiável não foi carregado (nem os filhos)
        linhas.append("    " * nivel + f"{disp.rotulo} {texto}")
        filhos = sorted(disp.filhos, key=lambda f: Decimal(f.ordem_sequencial))
        for f in filhos:
            _emit(f, nivel + 1)

    artigos = sorted(norma.dispositivos, key=lambda d: Decimal(d.ordem_sequencial))
    for art in artigos:
        _emit(art, 0)
    return "\n".join(linhas)
