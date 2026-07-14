import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st

from lib import consultas, estilo

st.set_page_config(page_title="CNPJ — Panorama Brasil", page_icon="📊", layout="wide")

st.title("Dados Abertos CNPJ — Panorama Brasil")
st.caption(f"Safra {consultas.safra_atual()} · Receita Federal · consulta local via DuckDB")

r = consultas.resumo_geral()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Estabelecimentos", f"{r['estabelecimentos'] / 1e6:.1f} M")
c2.metric("Ativos", f"{r['ativos'] / 1e6:.1f} M",
          f"{r['ativos'] / r['estabelecimentos']:.1%} do total")
c3.metric("Empresas", f"{r['empresas'] / 1e6:.1f} M")
c4.metric("MEIs (opção ativa)", f"{r['meis'] / 1e6:.1f} M")

st.divider()

col_a, col_b = st.columns(2)
with col_a:
    sit = consultas.situacao_cadastral()
    st.plotly_chart(
        estilo.barras_h(sit, "situacao", "n", "Situação cadastral"),
        use_container_width=True,
    )
with col_b:
    uf = consultas.ativos_por_uf()
    st.plotly_chart(
        estilo.barras_h(uf.head(15), "uf", "ativos", "Estabelecimentos ativos por UF (top 15)"),
        use_container_width=True,
    )

cnae = consultas.top_cnaes()
cnae["cnae_principal"] = cnae["cnae_principal"].str.slice(0, 70)
st.plotly_chart(
    estilo.barras_h(cnae, "cnae_principal", "ativos", "Top 15 CNAEs — estabelecimentos ativos"),
    use_container_width=True,
)

st.caption("Detalhes por UF e região na página **Recorte UF**; consultas pontuais em **Consulta CNPJ**.")
