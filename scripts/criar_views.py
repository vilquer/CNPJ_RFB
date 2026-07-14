"""
Cria/atualiza o banco de consulta rfb.duckdb na raiz do repo, com views
apontando para a safra mais recente do Parquet e macros de consulta prontas.

Uso:
    python criar_views.py                # aponta pra ultima safra encontrada
    python criar_views.py --safra 2026-06

Rodar de novo apos converter uma safra nova (convert.py) para repontar as
views. Idempotente: CREATE OR REPLACE em tudo.

Consulta (de qualquer working directory):
    import duckdb; con = duckdb.connect('rfb.duckdb', read_only=True)
    con.sql("SELECT * FROM ficha_cnpj('00.000.000/0001-91')")
    con.sql("SELECT * FROM busca_nome('BANCO DO BRASIL') LIMIT 5")
"""

import argparse
import json
import sys
from pathlib import Path

import duckdb

BASE_DIR = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = Path(__file__).resolve().parent
PARQUET_DIR = BASE_DIR / "parquet"
DB_PATH = BASE_DIR / "rfb.duckdb"

TABELAS_PROPRIAS = ["empresas", "estabelecimentos", "socios", "simples"]
TABELAS_DOMINIO = ["cnaes", "motivos", "municipios", "naturezas", "paises", "qualificacoes"]
TODAS = TABELAS_PROPRIAS + TABELAS_DOMINIO


def detectar_safra() -> str:
    base = PARQUET_DIR / "tabela=empresas"
    safras = sorted(p.name.split("=", 1)[1] for p in base.glob("safra=*") if p.is_dir())
    if not safras:
        print("ERRO: nenhuma safra encontrada em parquet/tabela=empresas/.")
        sys.exit(1)
    return safras[-1]


def validar_safra(safra: str) -> None:
    faltando = [
        t for t in TODAS
        if not list((PARQUET_DIR / f"tabela={t}" / f"safra={safra}").glob("part-*.parquet"))
    ]
    if faltando:
        print(f"ERRO: safra {safra} incompleta no parquet/ — faltam: {faltando}")
        sys.exit(1)


def colunas_schema(nome: str) -> list[str]:
    schema = json.loads((SCHEMAS_DIR / f"{nome}.json").read_text(encoding="utf-8"))
    return [c["nome"] for c in schema["colunas"]]


def criar_views_base(con, safra: str) -> None:
    for t in TODAS:
        caminho = (PARQUET_DIR / f"tabela={t}" / f"safra={safra}" / "part-*.parquet").as_posix()
        con.execute(f"CREATE OR REPLACE VIEW {t} AS SELECT * FROM read_parquet('{caminho}')")


def criar_views_enriquecidas(con) -> None:
    # Prefixos evitam ambiguidade; nomes de coluna conferidos contra scripts/*.json
    e_cols = colunas_schema("estabelecimentos")
    s_cols = colunas_schema("socios")
    m_cols = colunas_schema("empresas")
    assert "cnae_fiscal_principal" in e_cols and "faixa_etaria" in s_cols and "porte_empresa" in m_cols

    con.execute("""
        CREATE OR REPLACE VIEW estabelecimentos_completos AS
        SELECT
            est.cnpj_basico || est.cnpj_ordem || est.cnpj_dv AS cnpj,
            emp.razao_social,
            est.nome_fantasia,
            CASE est.identificador_matriz_filial
                WHEN '1' THEN 'matriz' WHEN '2' THEN 'filial' END AS matriz_filial,
            CASE est.situacao_cadastral
                WHEN '01' THEN 'nula'     WHEN '1' THEN 'nula'
                WHEN '02' THEN 'ativa'    WHEN '2' THEN 'ativa'
                WHEN '03' THEN 'suspensa' WHEN '3' THEN 'suspensa'
                WHEN '04' THEN 'inapta'   WHEN '4' THEN 'inapta'
                WHEN '08' THEN 'baixada'  WHEN '8' THEN 'baixada'
                ELSE est.situacao_cadastral END AS situacao,
            est.data_situacao_cadastral,
            mot.descricao AS motivo_situacao,
            est.data_inicio_atividade,
            est.cnae_fiscal_principal,
            cna.descricao AS cnae_principal,
            est.cnae_fiscal_secundaria,
            emp.natureza_juridica,
            nat.descricao AS natureza,
            CASE emp.porte_empresa
                WHEN '00' THEN 'nao informado'
                WHEN '01' THEN 'micro'
                WHEN '03' THEN 'pequeno porte'
                WHEN '05' THEN 'demais'
                ELSE emp.porte_empresa END AS porte,
            emp.capital_social,
            est.tipo_logradouro, est.logradouro, est.numero, est.complemento,
            est.bairro, est.cep, est.uf,
            est.municipio AS municipio_codigo,
            mun.descricao AS municipio,
            est.nome_cidade_exterior,
            pai.descricao AS pais,
            est.ddd1, est.telefone1, est.ddd2, est.telefone2,
            est.correio_eletronico,
            est.situacao_especial, est.data_situacao_especial,
            est.cnpj_basico
        FROM estabelecimentos est
        LEFT JOIN empresas    emp ON est.cnpj_basico = emp.cnpj_basico
        LEFT JOIN cnaes       cna ON est.cnae_fiscal_principal = cna.codigo
        LEFT JOIN municipios  mun ON est.municipio = mun.codigo
        LEFT JOIN motivos     mot ON est.motivo_situacao_cadastral = mot.codigo
        LEFT JOIN paises      pai ON est.pais = pai.codigo
        LEFT JOIN naturezas   nat ON emp.natureza_juridica = nat.codigo
    """)

    con.execute("""
        CREATE OR REPLACE VIEW socios_completos AS
        SELECT
            soc.cnpj_basico,
            emp.razao_social AS empresa,
            CASE soc.identificador_socio
                WHEN '1' THEN 'pessoa juridica'
                WHEN '2' THEN 'pessoa fisica'
                WHEN '3' THEN 'estrangeiro'
                ELSE soc.identificador_socio END AS tipo_socio,
            soc.nome_socio_razao_social AS nome_socio,
            soc.cpf_cnpj_socio,
            qua.descricao AS qualificacao,
            soc.data_entrada_sociedade,
            CASE soc.faixa_etaria
                WHEN '0' THEN 'nao se aplica'
                WHEN '1' THEN '0-12' WHEN '2' THEN '13-20' WHEN '3' THEN '21-30'
                WHEN '4' THEN '31-40' WHEN '5' THEN '41-50' WHEN '6' THEN '51-60'
                WHEN '7' THEN '61-70' WHEN '8' THEN '71-80' WHEN '9' THEN '80+'
                ELSE soc.faixa_etaria END AS faixa_etaria,
            pai.descricao AS pais_socio,
            soc.representante_legal,
            soc.nome_representante,
            qur.descricao AS qualificacao_representante
        FROM socios soc
        LEFT JOIN empresas      emp ON soc.cnpj_basico = emp.cnpj_basico
        LEFT JOIN qualificacoes qua ON soc.qualificacao_socio = qua.codigo
        LEFT JOIN qualificacoes qur ON soc.qualificacao_representante_legal = qur.codigo
        LEFT JOIN paises        pai ON soc.pais = pai.codigo
    """)

    con.execute("""
        CREATE OR REPLACE VIEW empresas_completas AS
        SELECT
            emp.cnpj_basico,
            emp.razao_social,
            emp.natureza_juridica,
            nat.descricao AS natureza,
            qua.descricao AS qualificacao_responsavel_descr,
            emp.capital_social,
            CASE emp.porte_empresa
                WHEN '00' THEN 'nao informado'
                WHEN '01' THEN 'micro'
                WHEN '03' THEN 'pequeno porte'
                WHEN '05' THEN 'demais'
                ELSE emp.porte_empresa END AS porte,
            emp.ente_federativo_responsavel,
            sim.opcao_simples,
            sim.data_opcao_simples,
            sim.data_exclusao_simples,
            sim.opcao_mei,
            sim.data_opcao_mei,
            sim.data_exclusao_mei
        FROM empresas emp
        LEFT JOIN naturezas     nat ON emp.natureza_juridica = nat.codigo
        LEFT JOIN qualificacoes qua ON emp.qualificacao_responsavel = qua.codigo
        LEFT JOIN simples       sim ON emp.cnpj_basico = sim.cnpj_basico
    """)


def criar_macros(con) -> None:
    # regexp_replace tira ./-/espacos; aceita 14 digitos ou so o basico (8)
    con.execute("""
        CREATE OR REPLACE MACRO ficha_cnpj(cnpj_entrada) AS TABLE
        WITH alvo AS (
            SELECT regexp_replace(CAST(cnpj_entrada AS VARCHAR), '[^0-9]', '', 'g') AS num
        )
        SELECT ec.* FROM estabelecimentos_completos ec, alvo
        WHERE (length(alvo.num) >= 14 AND ec.cnpj = alvo.num[1:14])
           OR (length(alvo.num) < 14  AND ec.cnpj_basico = alvo.num[1:8])
    """)

    con.execute("""
        CREATE OR REPLACE MACRO socios_cnpj(cnpj_entrada) AS TABLE
        WITH alvo AS (
            SELECT regexp_replace(CAST(cnpj_entrada AS VARCHAR), '[^0-9]', '', 'g')[1:8] AS basico
        )
        SELECT sc.* FROM socios_completos sc, alvo
        WHERE sc.cnpj_basico = alvo.basico
    """)

    # Ordenacao de relevancia: matriz antes de filial, ativa antes de baixada,
    # nome mais curto primeiro (match mais "exato"). Sem isso, buscas com
    # centenas de resultados + LIMIT do consumidor escondem a matriz
    # (ex: 'Banrisul' tem ~800 resultados, quase todos agencias e fundos).
    con.execute("""
        CREATE OR REPLACE MACRO busca_nome(termo) AS TABLE
        SELECT cnpj, razao_social, nome_fantasia, matriz_filial, situacao,
               uf, municipio, cnae_principal
        FROM estabelecimentos_completos
        WHERE razao_social ILIKE '%' || termo || '%'
           OR nome_fantasia ILIKE '%' || termo || '%'
        ORDER BY (matriz_filial = 'matriz') DESC,
                 (situacao = 'ativa') DESC,
                 length(razao_social) ASC
    """)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--safra", help="Safra AAAA-MM (padrao: mais recente no parquet/)")
    args = parser.parse_args()

    safra = args.safra or detectar_safra()
    validar_safra(safra)

    con = duckdb.connect(str(DB_PATH))
    con.execute("SET memory_limit='12GB'")
    con.execute("SET threads=4")

    criar_views_base(con, safra)
    criar_views_enriquecidas(con)
    criar_macros(con)

    # Metadado da safra apontada: consumidores (app, notebooks) derivam a
    # data de referencia daqui em vez de hardcodar (ultimo dia do mes da safra).
    con.execute(f"""
        CREATE OR REPLACE VIEW safra_atual AS
        SELECT '{safra}' AS safra,
               last_day(strptime('{safra}', '%Y-%m')) AS data_referencia
    """)

    print(f"rfb.duckdb atualizado -> safra {safra}\n")
    print("Views base:        " + ", ".join(TODAS))
    print("Views enriquecidas: estabelecimentos_completos, socios_completos, empresas_completas")
    print("Macros:             ficha_cnpj(cnpj), socios_cnpj(cnpj), busca_nome(termo)\n")

    for t in ["empresas", "estabelecimentos", "socios", "simples"]:
        n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        print(f"  {t:20s} {n:>12,} linhas")
    con.close()


if __name__ == "__main__":
    main()
