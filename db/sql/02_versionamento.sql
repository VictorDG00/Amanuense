-- ============================================================================
-- MOTOR DE VERSIONAMENTO — 02_versionamento.sql
-- ============================================================================
-- Toda mutação legislativa passa por UMA destas funções. Nunca por INSERT/
-- UPDATE direto nas tabelas de versão. Cada função, numa única transação:
--
--   1. fecha a redação vigente (data_fim = data de vigência da nova)
--   2. abre a nova redação (numero_versao + 1)
--   3. registra o vínculo em RELACAO_NORMATIVA
--   4. abre (ou reaproveita) o estado consolidado em VERSAO_NORMA
--
-- A constraint EXCLUDE do schema garante que, mesmo com bug na aplicação,
-- jamais existirão duas redações vigentes sobrepostas.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 0. Helper: abre novo estado consolidado da norma (ou reaproveita o aberto
--    pelo MESMO evento). Garante: uma lei que altera 10 artigos na mesma
--    data gera UMA versão da norma, não dez.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_abrir_versao_norma(
    p_id_norma           BIGINT,
    p_norma_alteradora   BIGINT,
    p_data               DATE
) RETURNS BIGINT LANGUAGE plpgsql AS $$
DECLARE
    v_atual versao_norma%ROWTYPE;
    v_nova  BIGINT;
BEGIN
    SELECT * INTO v_atual
    FROM versao_norma
    WHERE id_norma = p_id_norma AND data_fim_vigencia IS NULL
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Norma % sem versão consolidada aberta', p_id_norma;
    END IF;

    -- mesmo evento (mesma alteradora, mesma data) já abriu versão? reaproveita
    IF v_atual.data_inicio_vigencia = p_data
       AND v_atual.norma_alteradora_id IS NOT DISTINCT FROM p_norma_alteradora THEN
        RETURN v_atual.id_versao;
    END IF;

    IF p_data < v_atual.data_inicio_vigencia THEN
        RAISE EXCEPTION 'Alteração retroativa a estado consolidado anterior '
                        '(norma %, data %): tratar manualmente', p_id_norma, p_data;
    END IF;

    UPDATE versao_norma
       SET data_fim_vigencia = p_data
     WHERE id_versao = v_atual.id_versao;

    INSERT INTO versao_norma (id_norma, numero_versao, data_inicio_vigencia,
                              norma_alteradora_id)
    VALUES (p_id_norma, v_atual.numero_versao + 1, p_data, p_norma_alteradora)
    RETURNING id_versao INTO v_nova;

    RETURN v_nova;
END $$;

-- ----------------------------------------------------------------------------
-- 1. Criar norma (cabeçalho + versão consolidada nº 1)
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_criar_norma(
    p_tipo            TEXT,
    p_numero          TEXT,
    p_ano             SMALLINT,
    p_data_publicacao DATE,
    p_ementa          TEXT DEFAULT NULL,
    p_nome_oficial    TEXT DEFAULT NULL,
    p_apelido         TEXT DEFAULT NULL,
    p_esfera          TEXT DEFAULT 'federal',
    p_orgao           TEXT DEFAULT NULL,
    p_urn_lexml       TEXT DEFAULT NULL,
    p_url_oficial     TEXT DEFAULT NULL
) RETURNS BIGINT LANGUAGE plpgsql AS $$
DECLARE
    v_id BIGINT;
BEGIN
    INSERT INTO norma (tipo, numero, ano, data_publicacao, ementa, nome_oficial,
                       apelido, esfera, orgao_emissor, urn_lexml, url_fonte_oficial)
    VALUES (p_tipo, p_numero, p_ano, p_data_publicacao, p_ementa, p_nome_oficial,
            p_apelido, p_esfera, p_orgao, p_urn_lexml, p_url_oficial)
    RETURNING id_norma INTO v_id;

    INSERT INTO versao_norma (id_norma, numero_versao, data_inicio_vigencia)
    VALUES (v_id, 1, p_data_publicacao);

    RETURN v_id;
END $$;

-- ----------------------------------------------------------------------------
-- 2. Inserir dispositivo
--    p_norma_introdutora NULL  → carga do texto ORIGINAL (sem relação normativa)
--    p_norma_introdutora valor → ACRÉSCIMO legislativo (ex.: art. 55-A incluído
--                                pela Lei 13.853/2019) — registra relação
--                                'acrescenta' e abre versão da norma
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_inserir_dispositivo(
    p_id_norma            BIGINT,
    p_tipo                TEXT,
    p_numero_rotulo       TEXT,
    p_id_canonico         TEXT,
    p_texto               TEXT,
    p_ordem               NUMERIC,
    p_data_vigencia       DATE,
    p_id_pai              BIGINT  DEFAULT NULL,
    p_id_agrupamento      BIGINT  DEFAULT NULL,
    p_norma_introdutora   BIGINT  DEFAULT NULL,
    p_dispositivo_origem  BIGINT  DEFAULT NULL   -- art. da lei que comanda o acréscimo
) RETURNS BIGINT LANGUAGE plpgsql AS $$
DECLARE
    v_id BIGINT;
BEGIN
    INSERT INTO dispositivo (id_norma, tipo, numero_rotulo, id_canonico,
                             ordem_sequencial, id_pai, id_agrupamento,
                             norma_introdutora_id, data_criacao_ordenamento)
    VALUES (p_id_norma, p_tipo, p_numero_rotulo, p_id_canonico,
            p_ordem, p_id_pai, p_id_agrupamento,
            p_norma_introdutora, p_data_vigencia)
    RETURNING id_dispositivo INTO v_id;

    INSERT INTO dispositivo_versao (id_dispositivo, numero_versao, evento, texto,
                                    data_inicio_vigencia, norma_alteradora_id)
    VALUES (v_id, 1, 'redacao_original', p_texto, p_data_vigencia,
            p_norma_introdutora);

    IF p_norma_introdutora IS NOT NULL THEN
        INSERT INTO relacao_normativa (id_norma_origem, id_dispositivo_origem,
                                       tipo_relacao, id_norma_destino,
                                       id_dispositivo_destino, data_efeito)
        VALUES (p_norma_introdutora, p_dispositivo_origem, 'acrescenta',
                p_id_norma, v_id, p_data_vigencia);

        PERFORM fn_abrir_versao_norma(p_id_norma, p_norma_introdutora,
                                      p_data_vigencia);
    END IF;

    RETURN v_id;
END $$;

-- ----------------------------------------------------------------------------
-- 3. Registrar ALTERAÇÃO de redação ("Art. X passa a vigorar com a seguinte
--    redação")
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_registrar_alteracao(
    p_id_dispositivo      BIGINT,
    p_novo_texto          TEXT,
    p_norma_alteradora    BIGINT,
    p_data_vigencia       DATE,
    p_dispositivo_origem  BIGINT DEFAULT NULL
) RETURNS BIGINT LANGUAGE plpgsql AS $$
DECLARE
    v_vigente    dispositivo_versao%ROWTYPE;
    v_id_norma   BIGINT;
    v_nova       BIGINT;
BEGIN
    SELECT * INTO v_vigente
    FROM dispositivo_versao
    WHERE id_dispositivo = p_id_dispositivo AND data_fim_vigencia IS NULL
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Dispositivo % não possui redação vigente', p_id_dispositivo;
    END IF;

    IF v_vigente.evento = 'revogacao' THEN
        RAISE EXCEPTION 'Dispositivo % está revogado. Restabelecimento exige novo '
                        'dispositivo expresso — não há repristinação automática '
                        '(LINDB, art. 2º, § 3º)', p_id_dispositivo;
    END IF;

    IF p_data_vigencia <= v_vigente.data_inicio_vigencia THEN
        RAISE EXCEPTION 'Vigência da nova redação (%) não pode preceder ou '
                        'coincidir com a da redação atual (%)',
                        p_data_vigencia, v_vigente.data_inicio_vigencia;
    END IF;

    -- fecha a redação anterior no dia em que a nova entra ([inicio, fim))
    UPDATE dispositivo_versao
       SET data_fim_vigencia = p_data_vigencia
     WHERE id_dispositivo_versao = v_vigente.id_dispositivo_versao;

    INSERT INTO dispositivo_versao (id_dispositivo, numero_versao, evento, texto,
                                    data_inicio_vigencia, norma_alteradora_id)
    VALUES (p_id_dispositivo, v_vigente.numero_versao + 1, 'alteracao',
            p_novo_texto, p_data_vigencia, p_norma_alteradora)
    RETURNING id_dispositivo_versao INTO v_nova;

    SELECT id_norma INTO v_id_norma
    FROM dispositivo WHERE id_dispositivo = p_id_dispositivo;

    INSERT INTO relacao_normativa (id_norma_origem, id_dispositivo_origem,
                                   tipo_relacao, id_norma_destino,
                                   id_dispositivo_destino, data_efeito)
    VALUES (p_norma_alteradora, p_dispositivo_origem, 'altera',
            v_id_norma, p_id_dispositivo, p_data_vigencia);

    PERFORM fn_abrir_versao_norma(v_id_norma, p_norma_alteradora, p_data_vigencia);

    RETURN v_nova;
END $$;

-- ----------------------------------------------------------------------------
-- 4. Registrar REVOGAÇÃO expressa
--    A revogação É uma versão: a final, com texto NULL — assim a consulta
--    temporal é uniforme ("a redação vigente em D" responde inclusive
--    'revogado'). p_cascata revoga também a subárvore (revogar o artigo
--    revoga seus parágrafos, incisos, alíneas...).
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_registrar_revogacao(
    p_id_dispositivo      BIGINT,
    p_norma_revogadora    BIGINT,
    p_data_vigencia       DATE,
    p_cascata             BOOLEAN DEFAULT TRUE,
    p_dispositivo_origem  BIGINT  DEFAULT NULL
) RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE
    v_alvo       BIGINT;
    v_vigente    dispositivo_versao%ROWTYPE;
    v_id_norma   BIGINT;
BEGIN
    SELECT id_norma INTO v_id_norma
    FROM dispositivo WHERE id_dispositivo = p_id_dispositivo;

    FOR v_alvo IN
        WITH RECURSIVE sub AS (
            SELECT id_dispositivo FROM dispositivo
             WHERE id_dispositivo = p_id_dispositivo
            UNION ALL
            SELECT d.id_dispositivo
              FROM dispositivo d JOIN sub s ON d.id_pai = s.id_dispositivo
             WHERE p_cascata
        )
        SELECT id_dispositivo FROM sub
    LOOP
        SELECT * INTO v_vigente
        FROM dispositivo_versao
        WHERE id_dispositivo = v_alvo AND data_fim_vigencia IS NULL
        FOR UPDATE;

        CONTINUE WHEN NOT FOUND OR v_vigente.evento = 'revogacao';

        UPDATE dispositivo_versao
           SET data_fim_vigencia = p_data_vigencia
         WHERE id_dispositivo_versao = v_vigente.id_dispositivo_versao;

        INSERT INTO dispositivo_versao (id_dispositivo, numero_versao, evento,
                                        texto, data_inicio_vigencia,
                                        norma_alteradora_id)
        VALUES (v_alvo, v_vigente.numero_versao + 1, 'revogacao',
                NULL, p_data_vigencia, p_norma_revogadora);

        INSERT INTO relacao_normativa (id_norma_origem, id_dispositivo_origem,
                                       tipo_relacao, id_norma_destino,
                                       id_dispositivo_destino, data_efeito)
        VALUES (p_norma_revogadora, p_dispositivo_origem, 'revoga',
                v_id_norma, v_alvo, p_data_vigencia);
    END LOOP;

    PERFORM fn_abrir_versao_norma(v_id_norma, p_norma_revogadora, p_data_vigencia);
END $$;

-- ============================================================================
-- LIMITES EXPLÍCITOS DO MOTOR (fronteiras honestas, conforme conversa)
-- ============================================================================
-- a) REVOGAÇÃO TÁCITA: não é automatizável. Registrar manualmente via
--    relacao_normativa (tipo 'conflito_potencial') com a análise em
--    'observacao'. A resolução é jurídica, não computacional.
-- b) VETO e VETO DERRUBADO: dispositivos vetados nunca entram em vigor;
--    derrubada de veto cria vigência posterior à publicação. Modelável
--    com evento adicional — fora do escopo desta v1.
-- c) RENUMERAÇÃO: o evento existe no enum, mas a v1 não move filhos
--    automaticamente. Caso raro; tratar caso a caso.
-- d) EFEITOS RETROATIVOS (ex.: declaração de inconstitucionalidade ex tunc):
--    exigem modelo BItemporal (vigência × conhecimento). Extensão futura:
--    coluna adicional de "período de registro" nas tabelas de versão.
-- ============================================================================
