"""
Baixa da API de localidades do IBGE o mapeamento municipio -> regioes
(intermediaria, imediata, mesorregiao) das 27 UFs e grava em
apoio/ibge_regioes_br.csv, com nome normalizado para join com os nomes
de municipio da RFB (que vem em maiusculas sem acento).

Rodar uma vez (e de novo so se o IBGE atualizar a malha).
    python scripts/baixar_regioes_ibge.py
"""

import csv
import difflib
import unicodedata
from pathlib import Path

import requests

API = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios?view=nivelado"
BASE_DIR = Path(__file__).resolve().parent.parent
DESTINO = BASE_DIR / "apoio" / "ibge_regioes_br.csv"
DB_PATH = BASE_DIR / "rfb.duckdb"


def normalizar(nome: str) -> str:
    """Mesma normalizacao validada no join do RS: sem acento, maiusculas,
    sem apostrofo, hifen vira espaco, espacos colapsados."""
    s = unicodedata.normalize("NFD", nome)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.upper().replace("'", "").replace("-", " ").split())


# Renomeacoes oficiais que similaridade textual nao alcanca:
# nome na RFB (normalizado) -> nome IBGE atual (normalizado), por UF.
MANUAL = {
    ("TO", "FORTALEZA DO TABOCAO"): "TABOCAO",
    ("TO", "SAO VALERIO DA NATIVIDADE"): "SAO VALERIO",
    ("RN", "BOA SAUDE"): "JANUARIO CICCO",
    ("RR", "SAO LUIZ"): "SAO LUIZ DO ANAUA",
}


def aliases_rfb(municipios: list[dict]) -> list[tuple[str, str, dict]]:
    """Nomes da RFB que nao batem com o IBGE por grafia (PARATI vs Paraty
    etc). Resolve por similaridade dentro da mesma UF e devolve linhas extras
    (alias) apontando pro mesmo municipio IBGE. Requer rfb.duckdb existente."""
    if not DB_PATH.exists():
        print("rfb.duckdb nao encontrado — pulando geracao de aliases da RFB.")
        return []
    import duckdb

    por_uf: dict[str, dict[str, dict]] = {}
    for m in municipios:
        por_uf.setdefault(m["UF-sigla"], {})[normalizar(m["municipio-nome"])] = m

    con = duckdb.connect(str(DB_PATH), read_only=True)
    rfb = con.execute("""
        SELECT uf, municipio, count(*) AS n FROM estabelecimentos_completos
        WHERE uf IS NOT NULL AND municipio IS NOT NULL AND uf <> 'EX'
        GROUP BY 1, 2
    """).fetchall()
    con.close()

    aliases = []
    for uf, nome_rfb, n in rfb:
        norm_rfb = normalizar(nome_rfb)
        candidatos = por_uf.get(uf, {})
        if norm_rfb in candidatos:
            continue
        manual = MANUAL.get((uf, norm_rfb))
        if manual and manual in candidatos:
            aliases.append((norm_rfb, uf, candidatos[manual]))
            print(f"  alias manual: {uf} {norm_rfb!r} -> IBGE {candidatos[manual]['municipio-nome']!r} ({n} estab.)")
            continue
        proximo = difflib.get_close_matches(norm_rfb, candidatos.keys(), n=1, cutoff=0.75)
        if proximo:
            aliases.append((norm_rfb, uf, candidatos[proximo[0]]))
            print(f"  alias: {uf} {norm_rfb!r} -> IBGE {candidatos[proximo[0]]['municipio-nome']!r} ({n} estab.)")
        else:
            print(f"  SEM RESOLUCAO: {uf} {nome_rfb!r} ({n} estab.) — fica fora do recorte regional")
    return aliases


def main():
    print("Baixando municipios do IBGE...")
    municipios = requests.get(API, timeout=60).json()
    print(f"{len(municipios)} municipios recebidos.")

    print("Resolvendo grafias divergentes da RFB...")
    aliases = aliases_rfb(municipios)

    DESTINO.parent.mkdir(exist_ok=True)
    with open(DESTINO, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "municipio_norm", "uf", "municipio_ibge", "codigo_ibge",
            "regiao_intermediaria", "regiao_imediata", "mesorregiao",
        ])
        for m in municipios:
            w.writerow([
                normalizar(m["municipio-nome"]),
                m["UF-sigla"],
                m["municipio-nome"],
                m["municipio-id"],
                m["regiao-intermediaria-nome"],
                m["regiao-imediata-nome"],
                m["mesorregiao-nome"],
            ])
        for norm_rfb, uf, m in aliases:
            w.writerow([
                norm_rfb, uf, m["municipio-nome"], m["municipio-id"],
                m["regiao-intermediaria-nome"], m["regiao-imediata-nome"],
                m["mesorregiao-nome"],
            ])
    ufs = {m["UF-sigla"] for m in municipios}
    print(f"Gravado {DESTINO} ({len(municipios)} municipios + {len(aliases)} aliases, {len(ufs)} UFs).")


if __name__ == "__main__":
    main()
