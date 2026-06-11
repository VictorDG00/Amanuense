-- ============================================================================
-- DEMONSTRAÇÃO — 03_demo_lgpd.sql
-- Caso real: o art. 65 da LGPD (Lei 13.709/2018), o dispositivo de vigência
-- mais reescrito da história recente:
--
--   2018: redação original — vacatio de 18 meses
--   2019: Lei 13.853 dá nova redação ao caput e ACRESCENTA incisos I e II
--         (e acrescenta o art. 55-A, criando a ANPD)
--   2020: Lei 14.010 ACRESCENTA o inciso I-A (adia sanções p/ 01/08/2021)
--
-- Exercita os três cenários debatidos: alteração, acréscimo de dispositivo
-- e acréscimo de FILHO entre irmãos existentes (I-A entre I e II → ordem 1.5).
--
-- NOTA ANTI-ALUCINAÇÃO (coerente com o propósito da base): textos marcados
-- [ILUSTRATIVO] são parafraseados e devem ser substituídos pela redação
-- oficial do Planalto na carga real. Reproduzir texto legal "de memória"
-- é exatamente o erro que esta base existe para impedir.
-- ============================================================================

DO $$
DECLARE
    v_lgpd    BIGINT;
    v_l13853  BIGINT;
    v_l14010  BIGINT;
    v_cap9    BIGINT;
    v_cap10   BIGINT;
    v_art65   BIGINT;
    v_art55a  BIGINT;
BEGIN
    ------------------------------------------------------------------
    -- 1. Normas (datas de publicação: conferir no DOU na carga real)
    ------------------------------------------------------------------
    v_lgpd := fn_criar_norma(
        'Lei', '13709', 2018::smallint, DATE '2018-08-15',
        'Dispõe sobre o tratamento de dados pessoais [...]',
        'Lei Geral de Proteção de Dados Pessoais', 'LGPD',
        'federal', 'Congresso Nacional',
        'urn:lex:br:federal:lei:2018-08-14;13709',
        'https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm');

    v_l13853 := fn_criar_norma(
        'Lei', '13853', 2019::smallint, DATE '2019-07-09',
        'Altera a Lei 13.709/2018 para dispor sobre a ANPD [...]',
        NULL, NULL, 'federal', 'Congresso Nacional',
        'urn:lex:br:federal:lei:2019-07-08;13853', NULL);

    v_l14010 := fn_criar_norma(
        'Lei', '14010', 2020::smallint, DATE '2020-06-12',
        'RJET — Regime Jurídico Emergencial e Transitório [...]',
        NULL, NULL, 'federal', 'Congresso Nacional',
        'urn:lex:br:federal:lei:2020-06-10;14010', NULL);

    ------------------------------------------------------------------
    -- 2. Agrupamentos da LGPD (eixo organizacional)
    ------------------------------------------------------------------
    INSERT INTO agrupamento (id_norma, tipo, numero_rotulo, nome, ordem_sequencial)
    VALUES (v_lgpd, 'capitulo', 'Capítulo IX',
            'Da Autoridade Nacional de Proteção de Dados (ANPD) [...]', 9)
    RETURNING id_agrupamento INTO v_cap9;

    INSERT INTO agrupamento (id_norma, tipo, numero_rotulo, nome, ordem_sequencial)
    VALUES (v_lgpd, 'capitulo', 'Capítulo X',
            'Disposições Finais e Transitórias', 10)
    RETURNING id_agrupamento INTO v_cap10;

    ------------------------------------------------------------------
    -- 3. Art. 65 — redação ORIGINAL (2018)
    ------------------------------------------------------------------
    v_art65 := fn_inserir_dispositivo(
        p_id_norma       => v_lgpd,
        p_tipo           => 'artigo',
        p_numero_rotulo  => 'Art. 65.',
        p_id_canonico    => 'art65',
        p_texto          => 'Esta Lei entra em vigor após decorridos 18 '
                            '(dezoito) meses de sua publicação oficial.',
        p_ordem          => 65,
        p_data_vigencia  => DATE '2018-08-15',
        p_id_agrupamento => v_cap10);

    ------------------------------------------------------------------
    -- 4. Lei 13.853/2019:
    --    (a) NOVA REDAÇÃO ao caput do art. 65
    --    (b) ACRESCENTA incisos I e II ao art. 65
    --    (c) ACRESCENTA o art. 55-A (Capítulo IX)
    ------------------------------------------------------------------
    PERFORM fn_registrar_alteracao(
        v_art65,
        'Esta Lei entra em vigor: [ILUSTRATIVO — redação dada pela '
        'Lei 13.853/2019; substituir pelo texto oficial]',
        v_l13853, DATE '2019-07-09');

    PERFORM fn_inserir_dispositivo(v_lgpd, 'inciso', 'I -', 'art65_inc1',
        '[ILUSTRATIVO] dia 28 de dezembro de 2018, quanto aos arts. 55-A a 55-L e 58-A e 58-B;',
        1, DATE '2019-07-09', v_art65, NULL, v_l13853);

    PERFORM fn_inserir_dispositivo(v_lgpd, 'inciso', 'II -', 'art65_inc2',
        '[ILUSTRATIVO] 24 (vinte e quatro) meses após a publicação, quanto aos demais artigos.',
        2, DATE '2019-07-09', v_art65, NULL, v_l13853);

    v_art55a := fn_inserir_dispositivo(v_lgpd, 'artigo', 'Art. 55-A.', 'art55a',
        '[ILUSTRATIVO] Fica criada, sem aumento de despesa, a Autoridade '
        'Nacional de Proteção de Dados (ANPD) [...]',
        55.1,                       -- NUMERIC: entra entre o 55 e o 56
        DATE '2019-07-09', NULL, v_cap9, v_l13853);

    ------------------------------------------------------------------
    -- 5. Lei 14.010/2020: ACRESCENTA o inciso I-A entre I e II
    ------------------------------------------------------------------
    PERFORM fn_inserir_dispositivo(v_lgpd, 'inciso', 'I-A -', 'art65_inc1a',
        '[ILUSTRATIVO] dia 1º de agosto de 2021, quanto aos arts. 52, 53 e 54;',
        1.5,                        -- NUMERIC: entra entre I (1) e II (2)
        DATE '2020-06-12', v_art65, NULL, v_l14010);

    RAISE NOTICE 'Seed concluído. LGPD id=%', v_lgpd;
END $$;

-- ============================================================================
-- CONSULTAS DE VERIFICAÇÃO
-- ============================================================================

\echo ''
\echo '=== A) HISTÓRICO COMPLETO do art. 65 (toda a linha do tempo) ==='
SELECT dv.numero_versao AS v,
       dv.evento,
       daterange(dv.data_inicio_vigencia, dv.data_fim_vigencia, '[)') AS vigencia,
       coalesce(alt.tipo || ' ' || alt.numero || '/' || alt.ano,
                '(original)')                                          AS redacao_dada_por,
       left(dv.texto, 60) || '…'                                      AS texto
FROM dispositivo d
JOIN dispositivo_versao dv ON dv.id_dispositivo = d.id_dispositivo
LEFT JOIN norma alt        ON alt.id_norma = dv.norma_alteradora_id
WHERE d.id_canonico = 'art65'
ORDER BY dv.numero_versao;

\echo ''
\echo '=== B) MÁQUINA DO TEMPO: o art. 65 e filhos em 3 datas distintas ==='
\echo '--- Em 01/01/2019 (redação original, sem incisos):'
SELECT fn_texto_consolidado(n.id_norma, DATE '2019-01-01')
FROM norma n WHERE n.apelido = 'LGPD';

\echo '--- Em 01/12/2019 (pós Lei 13.853: caput novo + incisos I e II + art. 55-A):'
SELECT fn_texto_consolidado(n.id_norma, DATE '2019-12-01')
FROM norma n WHERE n.apelido = 'LGPD';

\echo '--- Hoje (pós Lei 14.010: inciso I-A entre I e II):'
SELECT fn_texto_consolidado(n.id_norma)
FROM norma n WHERE n.apelido = 'LGPD';

\echo ''
\echo '=== C) VERIFICAÇÃO DE CITAÇÃO (caso de uso central) ==='
\echo '--- "O art. 65, I-A, da LGPD" existia em 2019? E hoje?'
SELECT 'em 2019-12-01' AS consulta, * FROM (
    SELECT numero_rotulo, situacao, numero_versao
    FROM fn_consultar_dispositivo(
        (SELECT id_norma FROM norma WHERE apelido='LGPD'),
        'art65_inc1a', DATE '2019-12-01')) s
UNION ALL
SELECT 'hoje', numero_rotulo, situacao, numero_versao
FROM fn_consultar_dispositivo(
    (SELECT id_norma FROM norma WHERE apelido='LGPD'), 'art65_inc1a');

\echo ''
\echo '=== D) REDE NORMATIVA: quem mexeu na LGPD, e como ==='
SELECT o.tipo || ' ' || o.numero || '/' || o.ano AS norma_origem,
       r.tipo_relacao,
       d.numero_rotulo                            AS dispositivo_atingido,
       r.data_efeito
FROM relacao_normativa r
JOIN norma o        ON o.id_norma = r.id_norma_origem
LEFT JOIN dispositivo d ON d.id_dispositivo = r.id_dispositivo_destino
WHERE r.id_norma_destino = (SELECT id_norma FROM norma WHERE apelido = 'LGPD')
ORDER BY r.data_efeito, d.ordem_sequencial;

\echo ''
\echo '=== E) ESTADOS CONSOLIDADOS da LGPD (versao_norma) ==='
\echo '    Nota: a Lei 13.853 fez 4 mutações e gerou UMA versão (v2)'
SELECT vn.numero_versao,
       daterange(vn.data_inicio_vigencia, vn.data_fim_vigencia, '[)') AS periodo,
       coalesce(alt.tipo || ' ' || alt.numero || '/' || alt.ano,
                '(texto original)')                                    AS consolidacao_por
FROM versao_norma vn
LEFT JOIN norma alt ON alt.id_norma = vn.norma_alteradora_id
WHERE vn.id_norma = (SELECT id_norma FROM norma WHERE apelido = 'LGPD')
ORDER BY vn.numero_versao;

-- ============================================================================
-- F) REVOGAÇÃO — demonstração da mecânica em transação REVERTIDA
--    (não polui a base real; mostra cascata e a "máquina do tempo")
-- ============================================================================
\echo ''
\echo '=== F) REVOGAÇÃO em cascata (transação revertida ao final) ==='
BEGIN;
DO $$
DECLARE
    v_fict  BIGINT;
    v_lgpd  BIGINT := (SELECT id_norma FROM norma WHERE apelido = 'LGPD');
    v_art65 BIGINT := (SELECT id_dispositivo FROM dispositivo
                       WHERE id_norma = v_lgpd AND id_canonico = 'art65');
BEGIN
    v_fict := fn_criar_norma('Lei', '99999', 2099::smallint, DATE '2099-01-01',
                             'Norma fictícia para demonstração');
    -- revoga o art. 65 COM cascata: incisos I, I-A e II caem juntos
    PERFORM fn_registrar_revogacao(v_art65, v_fict, DATE '2099-01-01',
                                   p_cascata => TRUE);
    RAISE NOTICE E'\nConsolidado em 2099 (pós-revogação):\n%',
                 fn_texto_consolidado(v_lgpd, DATE '2099-06-01');
    RAISE NOTICE E'\nConsolidado HOJE (intacto — a revogação só vale de 2099 em diante):\n%',
                 fn_texto_consolidado(v_lgpd);
END $$;
ROLLBACK;
\echo '(rollback executado — base de demonstração permanece íntegra)'

-- ============================================================================
-- G) PROVA DA BLINDAGEM: tentar criar vigência sobreposta → o banco rejeita
-- ============================================================================
\echo ''
\echo '=== G) Tentativa de sobreposição de vigência (deve FALHAR) ==='
DO $$
DECLARE
    v_art65 BIGINT := (SELECT d.id_dispositivo FROM dispositivo d
                       JOIN norma n ON n.id_norma = d.id_norma
                       WHERE n.apelido = 'LGPD' AND d.id_canonico = 'art65');
BEGIN
    -- INSERT direto, burlando as functions: período colide com a v2 vigente
    INSERT INTO dispositivo_versao (id_dispositivo, numero_versao, evento,
                                    texto, data_inicio_vigencia)
    VALUES (v_art65, 99, 'alteracao', 'texto intruso', DATE '2020-01-01');
    RAISE NOTICE 'ERRO: a inserção deveria ter sido bloqueada!';
EXCEPTION WHEN exclusion_violation THEN
    RAISE NOTICE 'OK — constraint EXCLUDE bloqueou a sobreposição, como esperado.';
END $$;
