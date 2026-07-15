"""Queries do app. Todas cacheadas por parâmetro (st.cache_data) — a primeira
execução agrega dezenas de milhões de linhas (segundos), as demais são
instantâneas. Espelham as queries validadas nos notebooks de EDA.

Todo acesso ao banco via db.query()/db.query_um() (serializado — ver db.py)."""

import pandas as pd
import streamlit as st

from lib import db

UFS = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS",
       "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC",
       "SE", "SP", "TO"]


def _filtro_uf(uf: str | None) -> str:
    return f"AND uf = '{uf}'" if uf else ""


# ---------- metadados ----------

@st.cache_data
def safra_atual() -> str:
    """Safra apontada pelas views do rfb.duckdb (ex: '2026-07')."""
    try:
        return db.query_um("SELECT safra FROM safra_atual")[0]
    except Exception:
        return "?"  # banco antigo, sem a view safra_atual — rodar criar_views.py


# ---------- panorama ----------

@st.cache_data
def resumo_geral() -> dict:
    est = db.query_um("""
        SELECT count(*) AS total,
               count(*) FILTER (situacao = 'ativa') AS ativos
        FROM estabelecimentos_completos
    """)
    emp = db.query_um("SELECT count(*) FROM empresas")[0]
    mei = db.query_um("SELECT count(*) FROM simples WHERE opcao_mei = 'S'")[0]
    return {"estabelecimentos": est[0], "ativos": est[1], "empresas": emp, "meis": mei}


@st.cache_data
def situacao_cadastral(uf: str | None = None) -> pd.DataFrame:
    return db.query(f"""
        SELECT COALESCE(situacao, 'sem informacao') AS situacao, count(*) AS n
        FROM estabelecimentos_completos
        WHERE 1=1 {_filtro_uf(uf)}
        GROUP BY 1 ORDER BY n DESC
    """)


@st.cache_data
def ativos_por_uf() -> pd.DataFrame:
    return db.query("""
        SELECT uf, count(*) AS ativos
        FROM estabelecimentos_completos
        WHERE situacao = 'ativa' AND uf IS NOT NULL
        GROUP BY uf ORDER BY ativos DESC
    """)


@st.cache_data
def top_cnaes(uf: str | None = None, limite: int = 15) -> pd.DataFrame:
    return db.query(f"""
        SELECT cnae_principal, count(*) AS ativos
        FROM estabelecimentos_completos
        WHERE situacao = 'ativa' AND cnae_principal IS NOT NULL {_filtro_uf(uf)}
        GROUP BY 1 ORDER BY ativos DESC LIMIT {limite}
    """)


# ---------- consulta pontual ----------

@st.cache_data
def ficha(cnpj: str) -> pd.DataFrame:
    return db.query("SELECT * FROM ficha_cnpj(?)", [cnpj])


@st.cache_data
def socios(cnpj: str) -> pd.DataFrame:
    return db.query("SELECT * FROM socios_cnpj(?)", [cnpj])


@st.cache_data
def busca_nome(termo: str, limite: int = 100) -> pd.DataFrame:
    # ORDER BY aqui fora: ordenacao dentro da macro e descartada pelo
    # otimizador quando consumida como subquery. Relevancia: match exato do
    # termo (fantasia ou razao) > matriz > ativa > nome mais curto.
    return db.query(f"""
        SELECT * FROM busca_nome($termo)
        ORDER BY (upper(coalesce(nome_fantasia, '')) = upper(trim($termo))
                  OR upper(razao_social) = upper(trim($termo))) DESC,
                 (matriz_filial = 'matriz') DESC,
                 (situacao = 'ativa') DESC,
                 length(razao_social) ASC
        LIMIT {limite}
    """, {"termo": termo})


@st.cache_data
def estabelecimentos_da_empresa(cnpj_basico: str) -> pd.DataFrame:
    return db.query("""
        SELECT cnpj, matriz_filial, situacao, uf, municipio, cnae_principal
        FROM estabelecimentos_completos WHERE cnpj_basico = ?
        ORDER BY matriz_filial, uf
    """, [cnpj_basico])


# ---------- recorte UF / regiões ----------

@st.cache_data
def resumo_uf(uf: str) -> dict:
    r = db.query_um(f"""
        SELECT count(*) AS total,
               count(*) FILTER (situacao = 'ativa') AS ativos,
               count(DISTINCT municipio) AS municipios
        FROM estabelecimentos_completos WHERE uf = '{uf}'
    """)
    return {"total": r[0], "ativos": r[1], "municipios": r[2]}


@st.cache_data
def regioes_da_uf(uf: str) -> pd.DataFrame:
    return db.query(f"""
        SELECT regiao_intermediaria,
               count(*) AS estabelecimentos,
               count(*) FILTER (situacao = 'ativa') AS ativos,
               count(DISTINCT municipio) AS municipios
        FROM estabelecimentos_regioes
        WHERE uf = '{uf}' AND regiao_intermediaria IS NOT NULL
        GROUP BY 1 ORDER BY ativos DESC
    """)


@st.cache_data
def municipios_da_regiao(uf: str, regiao: str, limite: int = 15) -> pd.DataFrame:
    return db.query("""
        SELECT municipio, count(*) AS ativos
        FROM estabelecimentos_regioes
        WHERE uf = ? AND regiao_intermediaria = ? AND situacao = 'ativa'
        GROUP BY 1 ORDER BY ativos DESC LIMIT ?
    """, [uf, regiao, limite])


# ---------- dinâmica empresarial ----------

@st.cache_data
def aberturas_por_ano(uf: str | None = None) -> pd.DataFrame:
    if uf:
        return db.query(f"""
            WITH base AS (
                SELECT CAST(substr(data_inicio_atividade, 1, 4) AS INT) AS ano,
                       count(*) AS brasil,
                       count(*) FILTER (uf = '{uf}') AS na_uf
                FROM estabelecimentos
                WHERE length(data_inicio_atividade) = 8
                  AND substr(data_inicio_atividade, 1, 4) BETWEEN '1985' AND '2025'
                GROUP BY 1
            )
            SELECT ano, na_uf AS aberturas, na_uf * 100.0 / brasil AS fatia_pct
            FROM base ORDER BY ano
        """)
    return db.query("""
        SELECT CAST(substr(data_inicio_atividade, 1, 4) AS INT) AS ano,
               count(*) AS aberturas
        FROM estabelecimentos
        WHERE length(data_inicio_atividade) = 8
          AND substr(data_inicio_atividade, 1, 4) BETWEEN '1985' AND '2025'
        GROUP BY 1 ORDER BY 1
    """)


@st.cache_data
def idade_na_baixa(uf: str | None = None) -> pd.DataFrame:
    return db.query(f"""
        SELECT least(floor(datediff('year',
                   strptime(data_inicio_atividade, '%Y%m%d'),
                   strptime(data_situacao_cadastral, '%Y%m%d'))), 30) AS anos,
               count(*) AS n
        FROM estabelecimentos_completos
        WHERE situacao = 'baixada' {_filtro_uf(uf)}
          AND length(data_inicio_atividade) = 8 AND data_inicio_atividade > '19000101'
          AND length(data_situacao_cadastral) = 8
          AND data_situacao_cadastral > data_inicio_atividade
        GROUP BY 1 HAVING anos >= 0 ORDER BY 1
    """)


@st.cache_data
def idade_das_ativas(uf: str | None = None) -> pd.DataFrame:
    return db.query(f"""
        SELECT least(floor(datediff('year',
                   strptime(data_inicio_atividade, '%Y%m%d'),
                   (SELECT data_referencia FROM safra_atual))), 50) AS anos,
               count(*) AS n
        FROM estabelecimentos_completos
        WHERE situacao = 'ativa' {_filtro_uf(uf)}
          AND length(data_inicio_atividade) = 8 AND data_inicio_atividade > '19000101'
        GROUP BY 1 HAVING anos >= 0 ORDER BY 1
    """)
