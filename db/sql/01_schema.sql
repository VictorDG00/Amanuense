-- ============================================================================
-- BASE DE LEGISLAÇÃO ESTRUTURADA — 01_schema.sql
-- PostgreSQL 14+  |  Articulação conforme LC 95/1998, art. 10
-- ============================================================================
--
-- DECISÃO ESTRUTURAL CENTRAL (correção sobre o modelo debatido em conversa):
--
--   O dispositivo é separado em DUAS tabelas:
--
--   DISPOSITIVO        = identidade estrutural estável ("o art. 65 da LGPD")
--   DISPOSITIVO_VERSAO = cada redação que esse dispositivo já teve no tempo
--
--   Motivo: se cada alteração criasse um NOVO registro de dispositivo,
--   os filhos (incisos, parágrafos) que apontam via id_pai ficariam
--   órfãos ou presos à redação revogada. A identidade nunca muda;
--   só a redação muda. Hierarquia e remissões apontam para a identidade.
--
-- CONVENÇÃO TEMPORAL: intervalos meio-abertos [inicio, fim)
--   data_inicio_vigencia = primeiro dia em que a redação vige
--   data_fim_vigencia    = primeiro dia em que a redação JÁ NÃO vige
--                          (= data_inicio da redação seguinte)
--   NULL em data_fim     = redação vigente hoje
--   Vantagem: impossível haver lacuna ou sobreposição entre versões.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS btree_gist;  -- p/ constraint de exclusão temporal

-- ============================================================================
-- 1. NORMA — a lei como um todo
-- ============================================================================
CREATE TABLE norma (
    id_norma              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tipo                  TEXT NOT NULL,        -- 'Lei', 'LC', 'MP', 'Decreto',
                                                -- 'Resolução BCB', 'Resolução CMN'...
                                                -- lista aberta de propósito
    numero                TEXT NOT NULL,        -- TEXT: preserva '13.709' vs '13709';
                                                -- normalizar na aplicação
    ano                   SMALLINT NOT NULL,
    nome_oficial          TEXT,                 -- nome dado pela própria lei, se houver
    apelido               TEXT,                 -- 'LGPD', 'Lei Maria da Penha' —
                                                -- essencial p/ resolver citações informais
    ementa                TEXT,
    data_publicacao       DATE NOT NULL,
    data_vigencia_inicio  DATE,                 -- ATENÇÃO: vigência escalonada
                                                -- (caso LGPD) NÃO cabe aqui — mora
                                                -- nos dispositivos. Este campo é
                                                -- apenas referencial da norma.
    data_vigencia_fim     DATE,
    status                TEXT NOT NULL DEFAULT 'vigente'
                          CHECK (status IN ('vigente','revogada','suspensa')),
    esfera                TEXT NOT NULL
                          CHECK (esfera IN ('federal','estadual','municipal')),
    orgao_emissor         TEXT,
    urn_lexml             TEXT UNIQUE,          -- identificador canônico persistente
                                                -- ex: urn:lex:br:federal:lei:2018-08-14;13709
    url_fonte_oficial     TEXT,
    url_texto_consolidado TEXT
);

CREATE INDEX idx_norma_tipo_num_ano ON norma (tipo, numero, ano);
CREATE INDEX idx_norma_apelido ON norma (lower(apelido));

-- ============================================================================
-- 2. VERSAO_NORMA — estados consolidados da norma ao longo do tempo
-- ============================================================================
-- Papel REVISADO em relação à conversa: esta tabela é um LOG de marcos de
-- consolidação, não o "dono" dos dispositivos. Os dispositivos NÃO apontam
-- para cá (o id_versao que existia em DISPOSITIVO foi removido — ver nota
-- ao final do arquivo). A ligação dispositivo↔versão é TEMPORAL, por data.
--
-- Regra de ouro: uma lei alteradora que mexe em 10 artigos gera UMA nova
-- versão da norma, não dez. (Garantido por fn_abrir_versao_norma, no 02.)
-- ============================================================================
CREATE TABLE versao_norma (
    id_versao             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_norma              BIGINT NOT NULL REFERENCES norma (id_norma),
    numero_versao         INT NOT NULL,          -- 1 = texto original
    data_inicio_vigencia  DATE NOT NULL,
    data_fim_vigencia     DATE,                  -- NULL = estado atual
    norma_alteradora_id   BIGINT REFERENCES norma (id_norma),  -- NULL na v1
    texto_integral_md     TEXT,                  -- snapshot OPCIONAL (materializável
                                                 -- via fn_texto_consolidado)
    UNIQUE (id_norma, numero_versao),
    CONSTRAINT versao_norma_sem_sobreposicao
        EXCLUDE USING gist (
            id_norma WITH =,
            daterange(data_inicio_vigencia, data_fim_vigencia, '[)') WITH &&
        )
);

-- ============================================================================
-- 3. AGRUPAMENTO — estrutura organizacional ACIMA do artigo
--    (Parte > Livro > Título > Capítulo > Seção > Subseção — LC 95, art. 10, V)
-- ============================================================================
CREATE TABLE agrupamento (
    id_agrupamento        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_norma              BIGINT NOT NULL REFERENCES norma (id_norma),
    tipo                  TEXT NOT NULL
                          CHECK (tipo IN ('parte','livro','titulo','capitulo',
                                          'secao','subsecao')),
    numero_rotulo         TEXT,                  -- 'Capítulo X' (nullable:
                                                 -- 'Disposições Preliminares')
    nome                  TEXT,                  -- 'Das Disposições Finais...'
    ordem_sequencial      NUMERIC NOT NULL,
    id_pai                BIGINT REFERENCES agrupamento (id_agrupamento),
    norma_introdutora_id  BIGINT REFERENCES norma (id_norma),  -- agrupamentos também
                                                 -- podem ser acrescidos por lei posterior
    data_inicio_vigencia  DATE,
    data_fim_vigencia     DATE
);

CREATE INDEX idx_agrupamento_norma ON agrupamento (id_norma, ordem_sequencial);

-- ============================================================================
-- 4. DISPOSITIVO — IDENTIDADE estrutural (nunca versionada)
-- ============================================================================
-- Dois eixos de hierarquia, conforme debatido:
--   artigo            → id_agrupamento (eixo organizacional; NULL se a lei
--                       não tem divisões — maioria das leis curtas)
--   parágrafo         → id_pai = artigo
--   inciso            → id_pai = artigo OU parágrafo
--   alínea            → id_pai = inciso
--   item              → id_pai = alínea
--   subitem           → id_pai = item
--
-- O texto do registro tipo 'artigo' é o CAPUT.
-- ============================================================================
CREATE TABLE dispositivo (
    id_dispositivo        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_norma              BIGINT NOT NULL REFERENCES norma (id_norma),
    tipo                  TEXT NOT NULL
                          CHECK (tipo IN ('artigo','paragrafo','inciso',
                                          'alinea','item','subitem')),
    numero_rotulo         TEXT NOT NULL,         -- 'Art. 65', '§ 2º', 'I-A', 'a)'
    id_canonico           TEXT NOT NULL,         -- chave de CITAÇÃO, inspirada no
                                                 -- fragmento de URN LexML:
                                                 -- 'art65', 'art65_inc1a',
                                                 -- 'art5_par2_inc3_ali_a', 'art55a'
                                                 -- É a ponte entre a citação textual
                                                 -- e o registro — núcleo do caso de
                                                 -- uso de verificação de afirmações.
    ordem_sequencial      NUMERIC NOT NULL,      -- NUMERIC, não INT: o art. 5º-A
                                                 -- entra como 5.1 entre 5 e 6;
                                                 -- o inciso I-A entra como 1.5
    id_pai                BIGINT REFERENCES dispositivo (id_dispositivo),
    id_agrupamento        BIGINT REFERENCES agrupamento (id_agrupamento),
    norma_introdutora_id  BIGINT REFERENCES norma (id_norma),
                                                 -- NULL  = consta da lei original
                                                 -- valor = acrescentado por esta norma
    data_criacao_ordenamento DATE,               -- quando passou a existir no mundo

    UNIQUE (id_norma, id_canonico),

    -- Artigo não tem pai-dispositivo (seu pai está no eixo AGRUPAMENTO);
    -- todos os demais tipos exigem pai.
    CONSTRAINT chk_pai_por_tipo CHECK (
        (tipo = 'artigo' AND id_pai IS NULL)
        OR (tipo <> 'artigo' AND id_pai IS NOT NULL)
    ),
    -- Só artigo se vincula a agrupamento.
    CONSTRAINT chk_agrupamento_so_artigo CHECK (
        tipo = 'artigo' OR id_agrupamento IS NULL
    )
);

CREATE INDEX idx_dispositivo_norma ON dispositivo (id_norma, tipo);
CREATE INDEX idx_dispositivo_pai   ON dispositivo (id_pai);

-- ============================================================================
-- 5. DISPOSITIVO_VERSAO — cada REDAÇÃO do dispositivo no tempo
-- ============================================================================
CREATE TABLE dispositivo_versao (
    id_dispositivo_versao BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_dispositivo        BIGINT NOT NULL REFERENCES dispositivo (id_dispositivo),
    numero_versao         INT NOT NULL,          -- 1 = redação original/de criação
    evento                TEXT NOT NULL
                          CHECK (evento IN ('redacao_original','alteracao',
                                            'revogacao','renumeracao')),
    texto                 TEXT,                  -- NULL quando evento = 'revogacao'
    data_inicio_vigencia  DATE NOT NULL,
    data_fim_vigencia     DATE,                  -- NULL = redação vigente
    norma_alteradora_id   BIGINT REFERENCES norma (id_norma),
                                                 -- quem deu ESTA redação;
                                                 -- NULL na redação original

    UNIQUE (id_dispositivo, numero_versao),

    CONSTRAINT chk_revogacao_sem_texto CHECK (
        (evento = 'revogacao' AND texto IS NULL)
        OR (evento <> 'revogacao' AND texto IS NOT NULL)
    ),

    -- A GARANTIA CENTRAL DO VERSIONAMENTO:
    -- é fisicamente impossível existirem duas redações do mesmo
    -- dispositivo com períodos de vigência sobrepostos.
    CONSTRAINT dispositivo_versao_sem_sobreposicao
        EXCLUDE USING gist (
            id_dispositivo WITH =,
            daterange(data_inicio_vigencia, data_fim_vigencia, '[)') WITH &&
        )
);

CREATE INDEX idx_dv_dispositivo ON dispositivo_versao (id_dispositivo,
                                                       data_inicio_vigencia);
-- Índice parcial: a consulta mais frequente é "redação vigente hoje"
CREATE UNIQUE INDEX idx_dv_vigente ON dispositivo_versao (id_dispositivo)
    WHERE data_fim_vigencia IS NULL;

-- ============================================================================
-- 6. RELACAO_NORMATIVA — vínculos explícitos entre normas/dispositivos
-- ============================================================================
CREATE TABLE relacao_normativa (
    id_relacao              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_norma_origem         BIGINT NOT NULL REFERENCES norma (id_norma),
    id_dispositivo_origem   BIGINT REFERENCES dispositivo (id_dispositivo),
                            -- ex.: o art. da lei alteradora que comanda a mudança
    tipo_relacao            TEXT NOT NULL
                            CHECK (tipo_relacao IN ('altera','revoga','acrescenta',
                                                    'regulamenta','suspende','remete',
                                                    'conflito_potencial')),
    id_norma_destino        BIGINT NOT NULL REFERENCES norma (id_norma),
    id_dispositivo_destino  BIGINT REFERENCES dispositivo (id_dispositivo),
    data_efeito             DATE,
    observacao              TEXT     -- p/ 'conflito_potencial': registrar a análise
                                     -- jurídica (revogação tácita NÃO é automatizável)
);

CREATE INDEX idx_rel_destino ON relacao_normativa (id_norma_destino, tipo_relacao);
CREATE INDEX idx_rel_origem  ON relacao_normativa (id_norma_origem);

-- ============================================================================
-- 7. CAMADA DE CONSULTA
-- ============================================================================

-- 7.1  Texto vigente HOJE de qualquer dispositivo
CREATE VIEW vw_dispositivo_vigente AS
SELECT n.tipo  AS tipo_norma,
       n.numero,
       n.ano,
       n.apelido,
       d.id_dispositivo,
       d.id_canonico,
       d.tipo  AS tipo_dispositivo,
       d.numero_rotulo,
       dv.numero_versao,
       dv.evento,
       dv.texto,
       dv.data_inicio_vigencia AS vigente_desde,
       alt.tipo || ' ' || alt.numero || '/' || alt.ano AS redacao_dada_por
FROM dispositivo d
JOIN norma n              ON n.id_norma = d.id_norma
JOIN dispositivo_versao dv ON dv.id_dispositivo = d.id_dispositivo
                          AND dv.data_fim_vigencia IS NULL
LEFT JOIN norma alt       ON alt.id_norma = dv.norma_alteradora_id;

-- 7.2  Consulta-chave do caso de uso (verificação de citação):
--      "qual era/é o texto do dispositivo X da norma Y na data D?"
CREATE OR REPLACE FUNCTION fn_consultar_dispositivo(
    p_id_norma    BIGINT,
    p_id_canonico TEXT,
    p_data        DATE DEFAULT CURRENT_DATE
) RETURNS TABLE (
    numero_rotulo    TEXT,
    situacao         TEXT,
    texto            TEXT,
    numero_versao    INT,
    vigente_de       DATE,
    vigente_ate      DATE,
    redacao_dada_por TEXT
) LANGUAGE sql STABLE AS $$
    SELECT d.numero_rotulo,
           CASE
             WHEN dv.id_dispositivo_versao IS NULL THEN 'inexistente na data'
             WHEN dv.evento = 'revogacao'          THEN 'revogado'
             ELSE 'vigente'
           END,
           dv.texto,
           dv.numero_versao,
           dv.data_inicio_vigencia,
           dv.data_fim_vigencia,
           alt.tipo || ' ' || alt.numero || '/' || alt.ano
    FROM dispositivo d
    LEFT JOIN dispositivo_versao dv
           ON dv.id_dispositivo = d.id_dispositivo
          AND daterange(dv.data_inicio_vigencia, dv.data_fim_vigencia, '[)') @> p_data
    LEFT JOIN norma alt ON alt.id_norma = dv.norma_alteradora_id
    WHERE d.id_norma = p_id_norma
      AND d.id_canonico = p_id_canonico;
$$;

-- 7.3  Reconstrução do texto consolidado da norma em QUALQUER data
--      (a "máquina do tempo" — deriva o consolidado a partir das versões)
CREATE OR REPLACE FUNCTION fn_texto_consolidado(
    p_id_norma BIGINT,
    p_data     DATE DEFAULT CURRENT_DATE
) RETURNS TEXT LANGUAGE sql STABLE AS $$
    WITH RECURSIVE arvore AS (
        -- raízes: artigos (id_pai IS NULL) com redação vigente na data
        SELECT d.id_dispositivo,
               d.numero_rotulo,
               dv.texto,
               dv.evento,
               ARRAY[d.ordem_sequencial] AS caminho,
               0 AS nivel
        FROM dispositivo d
        JOIN dispositivo_versao dv
          ON dv.id_dispositivo = d.id_dispositivo
         AND daterange(dv.data_inicio_vigencia, dv.data_fim_vigencia, '[)') @> p_data
        WHERE d.id_norma = p_id_norma
          AND d.id_pai IS NULL

        UNION ALL

        SELECT f.id_dispositivo,
               f.numero_rotulo,
               fv.texto,
               fv.evento,
               a.caminho || f.ordem_sequencial,
               a.nivel + 1
        FROM dispositivo f
        JOIN arvore a ON f.id_pai = a.id_dispositivo
        JOIN dispositivo_versao fv
          ON fv.id_dispositivo = f.id_dispositivo
         AND daterange(fv.data_inicio_vigencia, fv.data_fim_vigencia, '[)') @> p_data
    )
    SELECT string_agg(
             repeat('    ', nivel) || numero_rotulo || ' ' ||
             CASE WHEN evento = 'revogacao' THEN '(Revogado)'
                  ELSE coalesce(texto, '') END,
             E'\n' ORDER BY caminho)
    FROM arvore;
$$;

-- ============================================================================
-- NOTA DE REVISÃO (em relação ao modelo consolidado na conversa)
-- ============================================================================
-- 1. Removido DISPOSITIVO.id_versao (FK → VERSAO_NORMA). Era incoerente:
--    um dispositivo não alterado atravessa N versões da norma — uma FK
--    única não representa isso. A ligação correta é temporal (por data).
-- 2. DISPOSITIVO dividido em identidade + DISPOSITIVO_VERSAO. Sem isso,
--    alterar o caput de um artigo quebraria o id_pai de todos os incisos.
-- 3. Acrescentado 'parte' aos agrupamentos (LC 95/1998, art. 10, V) e
--    'subitem' já contemplado nos dispositivos.
-- 4. ordem_sequencial é NUMERIC (não INT) para acomodar 'art. 5º-A' e
--    'inciso I-A' sem renumerar os vizinhos.
-- 5. id_canonico criado como chave de citação — é o que liga a afirmação
--    da IA ("art. 65, I-A, da LGPD") ao registro verificável.
-- ============================================================================
