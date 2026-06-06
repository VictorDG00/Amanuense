# Amanuense — Vade Mecum do Futuro

Pipeline multi-agente que transforma PDFs de normas jurídicas em um grafo de conhecimento navegável, com foco inicial no ecossistema regulatório do Banco Central do Brasil (Pix e afins).

## O que faz

1. Você joga PDFs de normas em `corpus/raw/`
2. O pipeline converte, analisa e relaciona tudo via LLM (DeepSeek-V3)
3. O resultado é um grafo interativo navegável no browser

## Estrutura

```
corpus/
  raw/        # PDFs das normas (ignorado pelo git)
  parsed/     # Markdown extraído dos PDFs (gerado automaticamente)
pipeline/
  agents/     # Cada agente da sequência de análise
  graph/      # Builder, exporter e lógica de vigência
  parsers/    # Extração de estrutura (artigos, incisos, parágrafos)
  prompts/    # Prompts de sistema de cada agente (.md)
  schemas/    # Modelos Pydantic (nós, arestas, grafo)
  utils/      # Cliente LLM, fábrica de IDs, helpers
frontend/     # Visualizador HTML/JS com D3.js (sem build step)
output/       # Arquivos gerados (knowledge-graph.json, graph-data.js…)
intermediate/ # Estado entre runs (ignorado pelo git)
scripts/      # Utilitários de linha de comando
```

## Instalação

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # preencha DEEPSEEK_API_KEY
```

## Uso

### 1. Converter PDFs para Markdown

```bash
python scripts/parse_pdfs.py
```

Coloque os PDFs em `corpus/raw/` com nomes que correspondam aos IDs do corpus (ex: `resolucao-bcb-001-2020.pdf`). O script converte para `corpus/parsed/*.md`.

### 2. Rodar o pipeline completo

```bash
amanuense run
# ou
python scripts/run_pipeline.py
```

Opções úteis:

```bash
amanuense run --resume              # pula agentes com output existente
amanuense run --agent norm-analyzer # roda só um agente
amanuense run --file resolucao-bcb-001-2020  # processa só um documento
```

### 3. Validar o grafo gerado

```bash
amanuense validate
```

### 4. Visualizar no browser

```bash
amanuense serve          # http://localhost:8080
amanuense serve --port 3000
```

## Sequência de Agentes

| # | Agente | Entrada | Saída |
|---|--------|---------|-------|
| 1 | `corpus-scanner` | PDFs em `corpus/raw/` | `scan_manifest.json` |
| 2 | `norm-analyzer` | Manifest + parsed MDs | Nós do grafo (normas, artigos, incisos) |
| 3 | `hierarchy-analyzer` | Nós | Arestas de hierarquia normativa |
| 4 | `revocation-analyzer` | Nós | Arestas de revogação + log de vigência |
| 5 | `implication-analyzer` | Nós | Arestas de implicação implícita (LLM) |
| 6 | `domain-analyzer` | Nós | Nós de domínio + arestas de classificação |
| 7 | `graph-builder` | Todos os intermediários | `knowledge-graph.json` + arquivos de frontend |
| 8 | `graph-reviewer` | Grafo | Revisão de qualidade |
| 9 | `tour-builder` | Grafo | Tours guiados para o frontend |

## Variáveis de Ambiente

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `DEEPSEEK_API_KEY` | — | Chave da API DeepSeek (obrigatória) |
| `AMANUENSE_MODEL` | `deepseek-chat` | Modelo a usar |
| `AMANUENSE_MAX_TOKENS` | `8192` | Máximo de tokens por chamada |
| `AMANUENSE_CORPUS_DIR` | `corpus` | Diretório do corpus |
| `AMANUENSE_OUTPUT_DIR` | `output` | Diretório de saída |
| `AMANUENSE_INTERMEDIATE_DIR` | `intermediate` | Estado intermediário entre runs |

## Corpus MVP (Pix/BCB)

O `corpus-scanner` já conhece estes documentos por nome de arquivo:

- `resolucao-bcb-001-2020` — Regulamento do arranjo Pix
- `circular-bcb-3952-2019` — Regulamenta o arranjo Pix
- `circular-bcb-4027-2020` — Altera o Regulamento Pix (ITP)
- `circular-bcb-4080-2021` — Requisitos e procedimentos complementares
- `manual-requisitos-tecnicos-pix` — Manual de Requisitos Técnicos
- `manual-seguranca-pix` — Manual de Segurança

## Testes

```bash
pytest
ruff check pipeline/
mypy pipeline/
```
