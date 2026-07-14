import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from lib import consultas, estilo

st.set_page_config(page_title="Recorte UF", page_icon="🗺️", layout="wide")
st.title("Recorte por UF e região IBGE")
st.caption(f"Safra {consultas.safra_atual()}")

uf = st.selectbox("UF", consultas.UFS, index=consultas.UFS.index("RS"))

r = consultas.resumo_uf(uf)
geral = consultas.resumo_geral()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Estabelecimentos", f"{r['total'] / 1e6:.2f} M",
          f"{r['total'] / geral['estabelecimentos']:.1%} do Brasil")
c2.metric("Ativos", f"{r['ativos'] / 1e6:.2f} M",
          f"{r['ativos'] / geral['ativos']:.1%} dos ativos BR")
taxa_uf = r["ativos"] / r["total"]
taxa_br = geral["ativos"] / geral["estabelecimentos"]
c3.metric("Taxa de atividade", f"{taxa_uf:.1%}", f"{(taxa_uf - taxa_br) * 100:+.1f} p.p. vs BR")
c4.metric("Municípios", f"{r['municipios']:,}")

st.divider()

st.subheader("Regiões geográficas intermediárias (IBGE)")
reg = consultas.regioes_da_uf(uf)
if reg.empty:
    st.warning("Sem mapeamento de região pra esta UF.")
    st.stop()

reg["taxa"] = reg.ativos / reg.estabelecimentos * 100
col_a, col_b = st.columns(2)
with col_a:
    st.plotly_chart(
        estilo.barras_h(reg, "regiao_intermediaria", "ativos",
                        "Estabelecimentos ativos por região"),
        use_container_width=True,
    )
with col_b:
    st.plotly_chart(
        estilo.barras_h(reg, "regiao_intermediaria", "taxa",
                        "Taxa de atividade por região (%)",
                        cor=estilo.AQUA, fmt_hover=".1f"),
        use_container_width=True,
    )

regiao = st.selectbox("Detalhar região", reg.regiao_intermediaria.tolist())
mun = consultas.municipios_da_regiao(uf, regiao)
col_c, col_d = st.columns(2)
with col_c:
    st.plotly_chart(
        estilo.barras_h(mun, "municipio", "ativos",
                        f"Top municípios — {regiao}"),
        use_container_width=True,
    )
with col_d:
    cnae = consultas.top_cnaes(uf)
    cnae["cnae_principal"] = cnae["cnae_principal"].str.slice(0, 55)
    st.plotly_chart(
        estilo.barras_h(cnae, "cnae_principal", "ativos", f"Top 15 CNAEs — {uf}"),
        use_container_width=True,
    )
