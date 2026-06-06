# Amanuense — Instruções para Claude Code

## O que é o projeto

Pipeline multi-agente Python que transforma PDFs de normas jurídicas (foco BCB/Pix) em grafos de conhecimento navegáveis. Usa DeepSeek-V3 como LLM via API compatível com OpenAI. O cliente se chama `ClaudeClient` por razão histórica — internamente usa `openai.OpenAI` apontando para `api.deepseek.com`.

## Stack

- Python 3.11, Pydantic v2, Click, Rich
- `pdfplumber` + `pymupdf` para extração de PDF
- `networkx` para manipulação de grafo
- Frontend: HTML/JS + D3.js, sem build step
- LLM: DeepSeek-V3 (`deepseek-chat`)

## Estrutura crítica

```
pipeline/agents/     # Um arquivo por agente da sequência
pipeline/prompts/    # Prompt de sistema de cada agente (arquivo .md)
pipeline/schemas/    # Todos os tipos Pydantic — fonte da verdade do grafo
pipeline/graph/      # builder.py monta o grafo final a partir dos intermediários
pipeline/utils/claude_client.py  # LLMClient (alias ClaudeClient)
```

Cada agente lê de `intermediate/<run-id>/` e escreve seu output lá. O `graph-builder` consome todos os intermediários e escreve em `output/`.

## Convenções

- Nomes de IDs de nós: gerados por `pipeline/utils/id_factory.py` — sempre usar as funções `norma_id()`, `artigo_id()`, `inciso_id()`, `paragrafo_id()`.
- Schemas Pydantic ficam em `pipeline/schemas/` — novos tipos vão lá, nunca inline nos agentes.
- Prompts de agentes ficam em `pipeline/prompts/<agent-name>.md` — o `BaseAgent.load_prompt()` resolve o path.
- Novos agentes herdam de `BaseAgent` e implementam `run(intermediate_dir, corpus_dir)`.
- Registrar o agente novo em `AGENT_SEQUENCE` e no `_run_agent()` em `pipeline/run.py`.

## Comandos úteis

```bash
# Ambiente
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Rodar
amanuense run
amanuense run --resume          # pula agentes já processados
amanuense run --agent <nome>    # roda só um agente
amanuense validate              # valida knowledge-graph.json
amanuense serve                 # frontend em http://localhost:8080

# Converter PDFs
python scripts/parse_pdfs.py

# Qualidade
pytest
ruff check pipeline/
mypy pipeline/
```

## O que NÃO fazer

- Não commitar `.env`, `corpus/raw/`, `corpus/parsed/`, `intermediate/`.
- Não mudar a assinatura `run(intermediate_dir, corpus_dir)` dos agentes sem atualizar todos.
- Não criar novos schemas fora de `pipeline/schemas/` — o `graph-builder` valida com `model_validate`.
- Não usar `ClaudeClient` para chamar a API real da Anthropic — o nome é alias do DeepSeek.
