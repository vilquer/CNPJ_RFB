import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from lib import consultas, estilo

st.set_page_config(page_title="Dinâmica empresarial", page_icon="📈", layout="wide")
st.title("Dinâmica empresarial — aberturas, sobrevivência e longevidade")
st.caption(f"Safra {consultas.safra_atual()}")

opcoes = ["Brasil"] + consultas.UFS
escolha = st.selectbox("Recorte", opcoes)
uf = None if escolha == "Brasil" else escolha

st.subheader("Aberturas por ano (1985–2025)")
abert = consultas.aberturas_por_ano(uf)
st.plotly_chart(
    estilo.linha(abert, "ano", "aberturas", f"Estabelecimentos abertos por ano — {escolha}"),
    use_container_width=True,
)
if uf:
    st.plotly_chart(
        estilo.linha(abert, "ano", "fatia_pct",
                     f"Fatia de {uf} nas aberturas do Brasil (%)",
                     cor=estilo.AQUA, fmt_hover=".1f", sufixo_y="%"),
        use_container_width=True,
    )

st.divider()
col_a, col_b = st.columns(2)

with col_a:
    st.subheader("Sobrevivência: idade na baixa")
    baixa = consultas.idade_na_baixa(uf)
    total_b = baixa.n.sum()
    ate5 = baixa.loc[baixa.anos <= 5, "n"].sum() / total_b
    ate10 = baixa.loc[baixa.anos <= 10, "n"].sum() / total_b
    st.plotly_chart(
        estilo.barras_v(baixa, "anos", "n", "Anos entre abertura e baixa (30 = 30+)"),
        use_container_width=True,
    )
    m1, m2 = st.columns(2)
    m1.metric("Baixados com ≤ 5 anos", f"{ate5:.1%}")
    m2.metric("Baixados com ≤ 10 anos", f"{ate10:.1%}")

with col_b:
    st.subheader("Longevidade das ativas")
    ativas = consultas.idade_das_ativas(uf)
    total_a = ativas.n.sum()
    acumulado = ativas.n.cumsum()
    mediana = int(ativas.loc[acumulado >= total_a / 2, "anos"].iloc[0])
    vinte_mais = ativas.loc[ativas.anos >= 20, "n"].sum() / total_a
    st.plotly_chart(
        estilo.barras_v(ativas, "anos", "n",
                        "Idade atual das ativas (50 = 50+)", cor=estilo.AQUA),
        use_container_width=True,
    )
    m3, m4 = st.columns(2)
    m3.metric("Idade mediana", f"{mediana} anos")
    m4.metric("Ativas com 20+ anos", f"{vinte_mais:.1%}")
