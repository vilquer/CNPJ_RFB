# Consultas — todos os dados de um CNPJ em uma única query

Exemplos de SQL que juntam todas as tabelas do `rfb.duckdb` (estabelecimentos,
empresas, simples, sócios + domínios) para uma única raiz de CNPJ.

Complementa o [dicionário de dados](dicionario_dados.md). Para consulta pontual
simples, a macro `ficha_cnpj('00.000.000/0001-91')` já existe no banco — as
queries abaixo valem quando se precisa de **tudo** em um resultado único.

## Regra de ouro de performance

**Sempre filtrar por `cnpj_basico` ANTES dos joins** (CTE `alvo` + JOIN nas
duas formas abaixo). O Parquet é ordenado por `cnpj_basico` e os zone maps
funcionam como índice: lookup pontual nos 72M de estabelecimentos sai em
~0,06s. Sem o pré-filtro, o join varre as tabelas inteiras e pode estourar o
`memory_limit` de 12GB (OOM já observado no grafo de vínculos).

Normalizar a entrada para raiz de 8 dígitos antes de usar:

```sql
SELECT substr(regexp_replace('00.000.000/0001-91', '[^0-9]', '', 'g'), 1, 8);
-- resultado: 00000000
```

## Forma 1 — uma linha por sócio

Grão: estabelecimento × sócio. Empresa com 5 filiais e 3 sócios devolve
15 linhas (dados de empresa/simples repetidos em todas). Bom para exportar
"flat" para planilha/CSV.

```sql
-- Trocar o valor de alvo pelo CNPJ desejado (só dígitos; 8 primeiros = raiz)
WITH alvo AS (SELECT '00000000' AS cnpj_basico)

SELECT
    -- Estabelecimento
    est.cnpj_basico || est.cnpj_ordem || est.cnpj_dv          AS cnpj,
    CASE est.identificador_matriz_filial
         WHEN '1' THEN 'matriz' ELSE 'filial' END             AS matriz_filial,
    est.nome_fantasia,
    CASE est.situacao_cadastral
         WHEN '01' THEN 'nula'     WHEN '1' THEN 'nula'
         WHEN '02' THEN 'ativa'    WHEN '2' THEN 'ativa'
         WHEN '03' THEN 'suspensa' WHEN '3' THEN 'suspensa'
         WHEN '04' THEN 'inapta'   WHEN '4' THEN 'inapta'
         WHEN '08' THEN 'baixada'  WHEN '8' THEN 'baixada'
         ELSE est.situacao_cadastral END                      AS situacao,
    est.data_situacao_cadastral,
    mot.descricao                                             AS motivo_situacao,
    est.data_inicio_atividade,
    est.cnae_fiscal_principal,
    cna.descricao                                             AS cnae_principal,
    est.cnae_fiscal_secundaria,
    est.tipo_logradouro, est.logradouro, est.numero,
    est.complemento, est.bairro, est.cep, est.uf,
    mun.descricao                                             AS municipio,
    est.nome_cidade_exterior,
    pai_est.descricao                                         AS pais_estabelecimento,
    est.ddd1, est.telefone1, est.ddd2, est.telefone2,
    est.correio_eletronico,
    est.situacao_especial, est.data_situacao_especial,

    -- Empresa
    emp.razao_social,
    nat.descricao                                             AS natureza_juridica,
    qua_resp.descricao                                        AS qualificacao_responsavel,
    emp.capital_social,
    CASE emp.porte_empresa
         WHEN '00' THEN 'não informado'
         WHEN '01' THEN 'microempresa'
         WHEN '03' THEN 'EPP'
         WHEN '05' THEN 'demais'
         ELSE emp.porte_empresa END                           AS porte,
    emp.ente_federativo_responsavel,

    -- Simples / MEI
    sim.opcao_simples, sim.data_opcao_simples, sim.data_exclusao_simples,
    sim.opcao_mei, sim.data_opcao_mei, sim.data_exclusao_mei,

    -- Sócio (uma linha por sócio; NULL se empresa sem quadro societário)
    CASE soc.identificador_socio
         WHEN '1' THEN 'pessoa jurídica'
         WHEN '2' THEN 'pessoa física'
         WHEN '3' THEN 'estrangeiro' END                      AS tipo_socio,
    soc.nome_socio_razao_social                               AS nome_socio,
    soc.cpf_cnpj_socio,
    qua_soc.descricao                                         AS qualificacao_socio,
    soc.data_entrada_sociedade,
    pai_soc.descricao                                         AS pais_socio,
    soc.representante_legal,
    soc.nome_representante,
    qua_rep.descricao                                         AS qualificacao_representante,
    CASE soc.faixa_etaria
         WHEN '1' THEN '0-12' WHEN '2' THEN '13-20' WHEN '3' THEN '21-30'
         WHEN '4' THEN '31-40' WHEN '5' THEN '41-50' WHEN '6' THEN '51-60'
         WHEN '7' THEN '61-70' WHEN '8' THEN '71-80' WHEN '9' THEN '80+'
         WHEN '0' THEN 'não se aplica' END                    AS faixa_etaria

FROM estabelecimentos est
JOIN alvo                 ON est.cnpj_basico = alvo.cnpj_basico
LEFT JOIN empresas emp    ON emp.cnpj_basico = est.cnpj_basico
LEFT JOIN simples  sim    ON sim.cnpj_basico = est.cnpj_basico
LEFT JOIN socios   soc    ON soc.cnpj_basico = est.cnpj_basico
LEFT JOIN cnaes         cna      ON cna.codigo      = est.cnae_fiscal_principal
LEFT JOIN motivos       mot      ON mot.codigo      = est.motivo_situacao_cadastral
LEFT JOIN municipios    mun      ON mun.codigo      = est.municipio
LEFT JOIN paises        pai_est  ON pai_est.codigo  = est.pais
LEFT JOIN naturezas     nat      ON nat.codigo      = emp.natureza_juridica
LEFT JOIN qualificacoes qua_resp ON qua_resp.codigo = emp.qualificacao_responsavel
LEFT JOIN qualificacoes qua_soc  ON qua_soc.codigo  = soc.qualificacao_socio
LEFT JOIN qualificacoes qua_rep  ON qua_rep.codigo  = soc.qualificacao_representante_legal
LEFT JOIN paises        pai_soc  ON pai_soc.codigo  = soc.pais
ORDER BY est.cnpj_ordem, soc.nome_socio_razao_social;
```

## Forma 2 — uma linha por estabelecimento, sócios agregados em lista

Sem multiplicação de linhas: a mesma empresa com 5 filiais e 3 sócios devolve
5 linhas, cada uma com a lista de sócios aninhada (LIST de STRUCT do DuckDB).
Aproveita `estabelecimentos_completos` (domínios já resolvidos).

```sql
WITH alvo AS (SELECT '00000000' AS cnpj_basico),
socios_agg AS (
    SELECT
        soc.cnpj_basico,
        list(struct_pack(
            nome         := soc.nome_socio_razao_social,
            documento    := soc.cpf_cnpj_socio,
            qualificacao := qua.descricao,
            entrada      := soc.data_entrada_sociedade
        ) ORDER BY soc.nome_socio_razao_social)               AS socios
    FROM socios soc
    JOIN alvo ON soc.cnpj_basico = alvo.cnpj_basico
    LEFT JOIN qualificacoes qua ON qua.codigo = soc.qualificacao_socio
    GROUP BY soc.cnpj_basico
)
SELECT ec.*, sa.socios,
       sim.opcao_simples, sim.opcao_mei
FROM estabelecimentos_completos ec
JOIN alvo ON ec.cnpj_basico = alvo.cnpj_basico
LEFT JOIN socios_agg sa ON sa.cnpj_basico = ec.cnpj_basico
LEFT JOIN simples   sim ON sim.cnpj_basico = ec.cnpj_basico
ORDER BY ec.cnpj;
```

## Observações

- `situacao_cadastral` vem com zero à esquerda (`02` ativa, `08` baixada) —
  o CASE da forma 1 cobre as duas grafias; a forma 2 herda o decode da view.
- Todos os joins de domínio são LEFT JOIN: código sem correspondência no
  domínio não derruba a linha.
- `cpf_cnpj_socio` de sócio PF já vem mascarado pela RFB na origem.
- `cnae_fiscal_secundaria` traz múltiplos códigos separados por vírgula no
  mesmo campo; para descrever cada um, `unnest(string_split(..., ','))` e
  join com `cnaes` — fora do escopo destes exemplos.
- Uso via Python:

```python
import duckdb
con = duckdb.connect('rfb.duckdb', read_only=True)
df = con.sql(query).df()   # query = SQL acima com o cnpj_basico desejado
```
