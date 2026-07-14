import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from lib import consultas

st.set_page_config(page_title="Consulta CNPJ", page_icon="🔎", layout="wide")
st.title("Consulta CNPJ")
st.caption(f"Safra {consultas.safra_atual()}")

entrada = st.text_input(
    "CNPJ (14 ou 8 dígitos, com ou sem pontuação) ou parte do nome",
    placeholder="00.000.000/0001-91  ·  BANCO DO BRASIL",
)


def mostrar_ficha(cnpj: str) -> None:
    f = consultas.ficha(cnpj)
    if f.empty:
        st.warning("CNPJ não encontrado.")
        return
    for _, linha in f.iterrows():
        e = linha.to_dict()  # acesso por chave: robusto a coluna ausente
        rotulo_situacao = {"ativa": "🟢", "baixada": "🔴", "suspensa": "🟡",
                           "inapta": "🟠"}.get(e.get("situacao"), "⚪")
        with st.container(border=True):
            st.subheader(e.get("razao_social") or "(sem razão social)")
            st.markdown(
                f"**CNPJ** `{e.get('cnpj')}` · {e.get('matriz_filial') or '?'} · "
                f"{rotulo_situacao} **{e.get('situacao')}** desde {e.get('data_situacao_cadastral') or '?'}"
                + (f" ({e.get('motivo_situacao')})"
                   if e.get("motivo_situacao") and e.get("situacao") != "ativa" else "")
            )
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(
                    f"**Atividade**: {e.get('cnae_principal') or '?'}\n\n"
                    f"**Natureza**: {e.get('natureza') or '?'} · **Porte**: {e.get('porte') or '?'}\n\n"
                    f"**Capital social**: R$ {e.get('capital_social') or '?'}\n\n"
                    f"**Início de atividade**: {e.get('data_inicio_atividade') or '?'}"
                )
            with c2:
                endereco = " ".join(str(x) for x in [
                    e.get("tipo_logradouro"), e.get("logradouro"),
                    e.get("numero"), e.get("complemento"),
                ] if x) or "?"
                st.markdown(
                    f"**Endereço**: {endereco}\n\n"
                    f"{e.get('bairro') or ''} · {e.get('municipio') or '?'}/{e.get('uf') or '?'} · "
                    f"CEP {e.get('cep') or '?'}\n\n"
                    f"**Contato**: ({e.get('ddd1') or '?'}) {e.get('telefone1') or '?'} · "
                    f"{(e.get('correio_eletronico') or '').lower() or '?'}"
                )
        if e.get("nome_fantasia"):
            st.caption(f"Nome fantasia: {e.get('nome_fantasia')}")

    basico = f.iloc[0]["cnpj_basico"]

    soc = consultas.socios(basico)
    st.subheader(f"Quadro societário ({len(soc)})")
    if soc.empty:
        st.caption("Sem sócios registrados (comum em MEI/empresário individual).")
    else:
        st.dataframe(
            soc[["nome_socio", "tipo_socio", "cpf_cnpj_socio", "qualificacao",
                 "faixa_etaria", "data_entrada_sociedade"]],
            use_container_width=True, hide_index=True,
        )

    outros = consultas.estabelecimentos_da_empresa(basico)
    if len(outros) > 1:
        st.subheader(f"Estabelecimentos da empresa ({len(outros)})")
        st.dataframe(outros, use_container_width=True, hide_index=True)


if entrada:
    digitos = re.sub(r"\D", "", entrada)
    if digitos and (entrada.strip().replace(".", "").replace("/", "").replace("-", "").isdigit()):
        mostrar_ficha(entrada)
    else:
        resultados = consultas.busca_nome(entrada.strip())
        st.caption(f"{len(resultados)} resultado(s) — máx. 100. Refine o termo se cortou.")
        if not resultados.empty:
            selecionado = st.dataframe(
                resultados, use_container_width=True, hide_index=True,
                on_select="rerun", selection_mode="single-row",
            )
            linhas = selecionado.selection.rows if selecionado else []
            if linhas:
                st.divider()
                mostrar_ficha(resultados.iloc[linhas[0]]["cnpj"])
