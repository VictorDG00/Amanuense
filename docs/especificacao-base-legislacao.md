# Especificação — Base de Legislação Estruturada

**Propósito:** base de dados de legislação brasileira com versionamento temporal por dispositivo, usada para **verificação de afirmações e citações de IA** (anti-alucinação).

**Stack:** PostgreSQL 14+ (usa `btree_gist`). DDL canônico em `01_schema.sql`; motor de versionamento em `02_versionamento.sql`; demonstração validada (caso LGPD) em `03_demo_lgpd.sql`. Esta especificação descreve o modelo e o pipeline de conversão texto → BD.

---

## 1. Arquitetura de dados — 6 tabelas

| Tabela | Papel | Campos-chave |
|---|---|---|
| `norma` | A lei como um todo (cabeçalho) | `tipo`, `numero`, `ano`, `apelido`, `urn_lexml` (único), `data_publicacao`, `status`, `esfera`, `url_fonte_oficial` |
| `versao_norma` | Log de estados consolidados da norma (marcos de alteração) | `numero_versao`, `data_inicio/fim_vigencia`, `norma_alteradora_id`, `texto_integral_md` (snapshot opcional) |
| `agrupamento` | Eixo organizacional **acima** do artigo | `tipo` (parte\|livro\|titulo\|capitulo\|secao\|subsecao), `numero_rotulo`, `nome`, `id_pai` (self-FK), `ordem_sequencial` |
| `dispositivo` | **Identidade estável** do dispositivo — nunca versionada | `tipo` (artigo\|paragrafo\|inciso\|alinea\|item\|subitem), `numero_rotulo`, `id_canonico`, `ordem_sequencial` (NUMERIC), `id_pai`, `id_agrupamento`, `norma_introdutora_id` |
| `dispositivo_versao` | Cada **redação** do dispositivo no tempo | `numero_versao`, `evento` (redacao_original\|alteracao\|revogacao\|renumeracao), `texto`, `data_inicio/fim_vigencia`, `norma_alteradora_id` |
| `relacao_normativa` | Vínculos entre normas/dispositivos | `tipo_relacao` (altera\|revoga\|acrescenta\|regulamenta\|suspende\|remete\|conflito_potencial), origem/destino em norma e dispositivo, `data_efeito`, `observacao` |

---

## 2. Invariantes estruturais (não negociáveis)

1. **Identidade ≠ redação.** `dispositivo` é a identidade ("o art. 65 da LGPD") e nunca muda; `dispositivo_versao` guarda cada texto que ele já teve. Hierarquia (`id_pai`) e remissões apontam **sempre para a identidade** — por isso alterar o caput de um artigo não quebra os incisos.
2. **Dois eixos de hierarquia:**
   - Artigo → vincula-se a `agrupamento` via `id_agrupamento` (nullable: leis curtas não têm divisões). `id_pai` de artigo é sempre NULL.
   - Parágrafo → `id_pai` = artigo. Inciso → `id_pai` = artigo **ou** parágrafo. Alínea → inciso. Item → alínea. Subitem → item.
3. **Texto do registro tipo `artigo` = caput.**
4. **Convenção temporal meio-aberta `[inicio, fim)`:** `data_fim_vigencia` = primeiro dia em que a redação **já não** vige (= início da seguinte). `NULL` = vigente hoje. Sem lacunas, sem sobreposições.
5. **Blindagem física:** constraint `EXCLUDE USING gist` impede duas redações vigentes sobrepostas do mesmo dispositivo, mesmo com bug na aplicação. Idem para `versao_norma`.
6. **Revogação é uma versão:** evento `revogacao`, `texto = NULL`. A consulta temporal fica uniforme — "a redação vigente em D" responde inclusive "revogado".
7. **`ordem_sequencial` é NUMERIC:** dispositivos acrescidos entram entre os vizinhos sem renumerar (art. 5º-A → `5.1`; inciso I-A entre I e II → `1.5`).
8. **`norma_introdutora_id`:** NULL = consta do texto original; preenchido = dispositivo acrescentado por lei posterior (ex.: art. 55-A da LGPD ← Lei 13.853/2019).

---

## 3. Gramática do `id_canonico` (chave de citação)

É a ponte entre a citação textual ("art. 65, I-A, da LGPD") e o registro verificável. `UNIQUE (id_norma, id_canonico)`.

**Regras de formação:**
- Caminho completo do dispositivo, segmentos unidos por `_`, somente `[a-z0-9]` dentro de cada segmento.
- Prefixos fixos de 3 letras: `art`, `par`, `inc`, `ali`, `ite`, `sub`.
- Romanos → arábicos (III → `3`); ordinais sem símbolo (5º → `5`); sufixos alfabéticos minúsculos sem hífen (Art. 55-A → `art55a`; inciso I-A → `inc1a`).
- Parágrafo único → `parun`.

| Citação | id_canonico |
|---|---|
| Art. 65 | `art65` |
| Art. 65, I-A | `art65_inc1a` |
| Art. 5º, § 2º, III | `art5_par2_inc3` |
| Art. 5º, § 2º, III, "b" | `art5_par2_inc3_alib` |
| Art. 7º, parágrafo único | `art7_parun` |
| Art. 55-A | `art55a` |
| Alínea "a", item 1, subitem 1.1 | `..._alia_ite1_sub11` |

---

## 4. Pipeline de conversão texto → BD

### Etapa 0 — Fonte
- Leis federais: texto **compilado** do Planalto (`planalto.gov.br/ccivil_03/...`). Guardar `url_fonte_oficial` e URN LexML em `norma`.
- Atenção: páginas antigas do Planalto usam encoding `windows-1252`/`ISO-8859-1` e HTML inconsistente. Normalizar para UTF-8 antes do parsing.

### Etapa 1 — Parsing estrutural (HTML → árvore JSON intermediária)
Nunca carregar direto no banco: gerar primeiro uma **árvore JSON canônica** por norma (facilita teste, diff e idempotência).

Padrões de reconhecimento (LC 95/1998, art. 10 — pontos de partida, robustecer):
- Agrupamentos: `^(PARTE|LIVRO|TÍTULO|CAPÍTULO|Seção|Subseção)\s+[IVXLCDM]+` (nome do agrupamento na(s) linha(s) seguinte(s)).
- Artigo: `^Art\.\s*(\d+)(º)?(-[A-Z])?` — ordinal até o 9º **sem ponto** após ("Art. 5º Texto"); cardinal do 10 em diante **com ponto** ("Art. 10. Texto").
- Parágrafo: `^§\s*(\d+)(º)?` ou `^Parágrafo único\.`
- Inciso: `^([IVXLCDM]+)(-[A-Z])?\s*[-–—]`
- Alínea: `^([a-z])\)`
- Item: `^(\d+)\.` (apenas quando o contexto da pilha está em alínea — evita falso positivo). Subitem (`1.1`) é raro em lei, comum em atos infralegais (Resoluções BCB).

Montagem da hierarquia por **pilha de contexto**: ao encontrar um inciso, o pai é o último parágrafo aberto, senão o artigo corrente; e assim por diante.

### Etapa 2 — Extração de histórico (as anotações do Planalto são a fonte do versionamento)
O texto compilado do Planalto preserva o histórico inline:
- Redações anteriores aparecem **tachadas** (`<strike>`/CSS) — viram versões antigas.
- `(Redação dada pela Lei nº X, de AAAA)` → a redação corrente do dispositivo veio de X (evento `alteracao`).
- `(Incluído pela Lei nº X, de AAAA)` → `norma_introdutora_id` = X (evento `redacao_original` com introdutora).
- `(Revogado pela Lei nº X, de AAAA)` → evento `revogacao`.
- `(Vide ...)`, `(Vetado)`, `(Vigência)` → **não interpretar**: enviar para fila manual (§6).

### Etapa 3 — Carga (somente via funções do `02_versionamento.sql` — nunca INSERT direto)
1. `fn_criar_norma(...)` para a norma-alvo. Criar também **cabeçalho mínimo** de cada norma alteradora citada que ainda não exista na base (para as FKs).
2. Ordenar todos os eventos extraídos **cronologicamente** (data de publicação da norma alteradora) e aplicar em ordem:
   - Dispositivos originais → `fn_inserir_dispositivo(..., p_norma_introdutora => NULL)`.
   - Acréscimos → `fn_inserir_dispositivo(..., p_norma_introdutora => <id>)`.
   - Novas redações → `fn_registrar_alteracao(...)` (versão antiga primeiro, depois cada alteração em ordem).
   - Revogações → `fn_registrar_revogacao(...)` (cascata default: revogar artigo revoga a subárvore).
3. **Data de vigência da nova redação:** default = data de publicação da norma alteradora. Se a alteradora tiver vacatio ou cláusula de vigência própria → fila manual.
4. **Idempotência:** reexecutar a carga não pode duplicar. `UNIQUE (id_norma, id_canonico)` e `urn_lexml UNIQUE` protegem; o loader deve fazer skip/upsert por essas chaves.

### Etapa 4 — Validação pós-carga (critério de aceite)
- `fn_texto_consolidado(norma, hoje)` deve bater com o texto compilado do Planalto após normalização (espaços, tachados removidos). Diff vazio = aceito.
- Contagens: nº de artigos, parágrafos, incisos extraídos = nº carregado.
- Toda alteração/revogação/acréscimo deve ter linha correspondente em `relacao_normativa`.
- Teste de máquina do tempo: consolidado em data anterior à primeira alteração = texto original.

---

## 5. Regras do motor de versionamento (resumo do `02_versionamento.sql`)

- `fn_criar_norma` → cabeçalho + `versao_norma` nº 1.
- `fn_inserir_dispositivo` → identidade + versão 1; se `p_norma_introdutora` preenchida, registra relação `acrescenta` e abre versão da norma.
- `fn_registrar_alteracao` → fecha redação vigente em `[.., data)`, abre versão N+1, registra relação `altera`. Bloqueia alteração de dispositivo revogado (sem repristinação automática — LINDB, art. 2º, § 3º) e vigência retroativa.
- `fn_registrar_revogacao` → versão final com `texto NULL`; `p_cascata => TRUE` revoga a subárvore.
- `fn_abrir_versao_norma` (interno) → deduplica: **uma lei alteradora + uma data = uma versão da norma**, mesmo alterando 50 dispositivos.

## Interface de consulta
- `vw_dispositivo_vigente` — redação atual de tudo.
- `fn_consultar_dispositivo(id_norma, id_canonico, data)` — **a consulta de verificação de citação**: retorna `vigente | revogado | inexistente na data` + texto + quem deu a redação.
- `fn_texto_consolidado(id_norma, data)` — reconstrói a norma inteira em qualquer data (máquina do tempo).

---

## 6. Fila de revisão manual (não automatizar)

| Caso | Tratamento |
|---|---|
| Revogação tácita / conflito de normas | `relacao_normativa` tipo `conflito_potencial` + análise em `observacao` |
| Veto e derrubada de veto | Fora da v1; marcar e não carregar o dispositivo |
| Renumeração de dispositivos | Evento existe no enum; aplicar caso a caso |
| Vigência escalonada ou vacatio da alteradora | Ajustar `data_inicio_vigencia` manualmente |
| Decisão judicial com efeito retroativo (ex tunc) | Exige modelo bitemporal — extensão futura |
| Anotações `(Vide)`, `(Vetado)`, texto ilegível/PDF escaneado | Log + revisão humana |

---

## 7. Diretriz anti-alucinação do próprio pipeline

Nenhum texto legal entra na base "de memória" do modelo: **todo** `texto` de `dispositivo_versao` deve vir do parsing da fonte oficial, com `url_fonte_oficial` rastreável. Se o parser não conseguir extrair com confiança, o dispositivo vai para a fila manual — nunca preenchido por inferência.
