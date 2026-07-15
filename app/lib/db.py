"""Conexão única (cached) com o rfb.duckdb, sempre read-only.

IMPORTANTE: Streamlit executa páginas/sessões em threads concorrentes e a
conexão DuckDB é uma só — execute().df() intercalado entre threads faz uma
thread consumir o resultado da outra (sintoma: .df() devolve None). Todo
acesso passa por query()/query_um(), serializado com lock.
"""

import threading
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

_LOCK = threading.Lock()

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "rfb.duckdb"
CSV_REGIOES = BASE_DIR / "apoio" / "ibge_regioes_br.csv"


@st.cache_resource
def conexao() -> duckdb.DuckDBPyConnection:
    if not DB_PATH.exists():
        st.error(
            f"`{DB_PATH}` não encontrado. Rode o pipeline primeiro: "
            "`python scripts/download.py AAAA-MM`, `python scripts/convert.py AAAA-MM`, "
            "`python scripts/criar_views.py`."
        )
        st.stop()
    con = duckdb.connect(str(DB_PATH), read_only=True)
    # 8GB (nao 12): app convive com notebooks/outros processos DuckDB na
    # mesma maquina de 24GB — dois processos de 12GB derrubam por overcommit.
    con.execute("SET memory_limit='8GB'")
    con.execute("SET threads=4")
    # View temporária com região IBGE resolvida (join por nome normalizado,
    # mesma regra do scripts/baixar_regioes_ibge.py)
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW estabelecimentos_regioes AS
        SELECT ec.*, r.regiao_intermediaria, r.regiao_imediata, r.mesorregiao
        FROM estabelecimentos_completos ec
        LEFT JOIN read_csv('{CSV_REGIOES.as_posix()}', header=true) r
          ON ec.uf = r.uf
         AND regexp_replace(
                 replace(replace(strip_accents(upper(ec.municipio)), '''', ''), '-', ' '),
                 ' +', ' ', 'g') = r.municipio_norm
    """)
    return con


def query(sql: str, params: list | None = None) -> pd.DataFrame:
    """Executa e devolve DataFrame, serializado — único jeito seguro de
    consultar a conexão compartilhada a partir das páginas."""
    con = conexao()
    with _LOCK:
        return con.execute(sql, params).df() if params else con.execute(sql).df()


def query_um(sql: str, params: list | None = None) -> tuple:
    """Executa e devolve a primeira linha (fetchone), serializado."""
    con = conexao()
    with _LOCK:
        r = con.execute(sql, params) if params else con.execute(sql)
        return r.fetchone()
