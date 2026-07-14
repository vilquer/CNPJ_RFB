"""
Converte os zips de uma safra (raw/{safra}/*.zip) para Parquet particionado
por tabela+safra, usando DuckDB e os schemas em scripts/*.json.

Uso:
    python convert.py 2026-06
    python convert.py 2026-06 --forcar        # reconverte mesmo se ja convertida
    python convert.py 2026-06 --manter-raw    # nao apaga raw/ e staging/ ao final

Le raw/{safra}/manifest.json para confirmar que a safra foi baixada antes de
converter. Ao final, por padrao apaga staging/{safra} e raw/{safra} (decisao
registrada no CLAUDE.md: reprocessar = rebaixar, aceito como trade-off).
"""

import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path

import duckdb

BASE_DIR = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR / "raw"
STAGING_DIR = BASE_DIR / "staging"
PARQUET_DIR = BASE_DIR / "parquet"

TABELAS_COM_SCHEMA_PROPRIO = ["empresas", "estabelecimentos", "socios", "simples"]


def carregar_jobs() -> list[dict]:
    """Monta a lista de tabelas a converter a partir dos schemas/*.json."""
    jobs = []
    for nome in TABELAS_COM_SCHEMA_PROPRIO:
        schema = json.loads((SCHEMAS_DIR / f"{nome}.json").read_text(encoding="utf-8"))
        jobs.append({
            "tabela": nome,
            "arquivos_origem": schema["arquivos_origem"],
            "colunas": [c["nome"] for c in schema["colunas"]],
            "delimitador": schema["delimitador"],
            "encoding": schema["encoding"],
        })

    dominios = json.loads((SCHEMAS_DIR / "dominios.json").read_text(encoding="utf-8"))
    colunas_dominio = [c["nome"] for c in dominios["colunas"]]
    for nome, info in dominios["tabelas"].items():
        jobs.append({
            "tabela": nome,
            "arquivos_origem": [info["arquivo_origem"]],
            "colunas": colunas_dominio,
            "delimitador": dominios["delimitador"],
            "encoding": dominios["encoding"],
        })
    return jobs


def carregar_manifest(safra_dir: Path) -> dict:
    manifest_path = safra_dir / "manifest.json"
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def parquet_completo(job: dict, safra: str) -> bool:
    parquet_dir = PARQUET_DIR / f"tabela={job['tabela']}" / f"safra={safra}"
    esperado = len(job["arquivos_origem"])
    return len(list(parquet_dir.glob("part-*.parquet"))) == esperado


# Bytes 0x80-0x9F sao invalidos no latin-1 estrito do DuckDB e aparecem como
# lixo raro nos CSVs da RFB (ex: 3 ocorrencias de 0x8F em 8 GB). Os encodings
# cp1252 do DuckDB (via ICU) decodificam errado nesta versao, entao filtramos
# esses bytes para '?' na extracao e usamos o caminho nativo latin-1.
_FILTRO_C1 = bytes(0x3F if 0x80 <= b <= 0x9F else b for b in range(256))


def extrair_zip(zip_path: Path, destino: Path) -> list[Path]:
    destino.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for membro in zf.namelist():
            with zf.open(membro) as origem, open(destino / Path(membro).name, "wb") as saida:
                while chunk := origem.read(1024 * 1024 * 8):
                    saida.write(chunk.translate(_FILTRO_C1))
    return [p for p in destino.iterdir() if p.is_file()]


def converter_tabela(con, job: dict, safra: str, raw_dir: Path, staging_dir: Path) -> bool:
    """Extrai os zips da tabela e converte cada um em um part-*.parquet. Retorna True se ok."""
    tabela = job["tabela"]
    parquet_dir = PARQUET_DIR / f"tabela={tabela}" / f"safra={safra}"

    faltando = [a for a in job["arquivos_origem"] if not (raw_dir / a).exists()]
    if faltando:
        print(f"  [{tabela}] pulando: arquivo(s) ausente(s) em raw/: {faltando}")
        return False

    parquet_dir.mkdir(parents=True, exist_ok=True)
    colunas_sql = ", ".join(f"'{c}': 'VARCHAR'" for c in job["colunas"])

    for idx, nome_zip in enumerate(job["arquivos_origem"]):
        part_path = parquet_dir / f"part-{idx}.parquet"
        if part_path.exists():
            print(f"  [{tabela}] {nome_zip}: part-{idx}.parquet ja existe, pulando.")
            continue

        csvs = extrair_zip(raw_dir / nome_zip, staging_dir / tabela / str(idx))
        if not csvs:
            print(f"  [{tabela}] ERRO: {nome_zip} nao contem arquivos apos extracao.")
            return False

        # Escreve em .tmp e renomeia no final: conversao interrompida nunca
        # deixa um part-*.parquet parcial que passaria por completo no resume.
        tmp_path = parquet_dir / f"part-{idx}.parquet.tmp"
        lista_csv = ", ".join(f"'{p.as_posix()}'" for p in csvs)
        con.execute(f"""
            COPY (
                SELECT * FROM read_csv(
                    [{lista_csv}],
                    delim='{job["delimitador"]}',
                    header=false,
                    encoding='{job["encoding"]}',
                    quote='"',
                    escape='"',
                    auto_detect=false,
                    strict_mode=false,
                    store_rejects=true,
                    columns={{{colunas_sql}}}
                )
            ) TO '{tmp_path.as_posix()}' (FORMAT PARQUET)
        """)
        # store_rejects pula linhas malformadas (ex: linhas digitadas em
        # caracteres fullwidth na origem RFB) mas as registra — reporta e zera.
        rejeitadas = con.execute("SELECT count(*) FROM reject_errors").fetchone()[0]
        if rejeitadas:
            exemplos = con.execute(
                "SELECT csv_line FROM reject_errors LIMIT 3"
            ).fetchall()
            print(f"  [{tabela}] AVISO: {rejeitadas} linha(s) rejeitada(s) em {nome_zip}:")
            for (linha,) in exemplos:
                print(f"    {linha[:100]}")
            con.execute("DELETE FROM reject_errors")
            con.execute("DELETE FROM reject_scans")
        tmp_path.replace(part_path)
        shutil.rmtree(staging_dir / tabela / str(idx), ignore_errors=True)
        print(f"  [{tabela}] {nome_zip} -> {part_path.relative_to(BASE_DIR)}")

    return True


def converter_safra(safra: str, forcar: bool = False, manter_raw: bool = False) -> None:
    raw_dir = RAW_DIR / safra
    staging_dir = STAGING_DIR / safra
    jobs = carregar_jobs()

    ja_convertida = all(parquet_completo(job, safra) for job in jobs)
    if ja_convertida and not forcar:
        print(f"Safra {safra}: ja convertida em parquet/ (use --forcar para reconverter).")
        return

    if not raw_dir.exists():
        print(f"ERRO: raw/{safra} nao existe e a safra nao esta convertida. Rode download.py primeiro.")
        sys.exit(1)

    manifest = carregar_manifest(raw_dir)
    if manifest.get("status_geral") not in ("baixado", "convertido"):
        print(f"ERRO: safra {safra} nao esta com status 'baixado' no manifest. Rode download.py primeiro.")
        sys.exit(1)

    con = duckdb.connect()
    # Sem limite o DuckDB usa ~80% da RAM e ja derrubou a maquina convertendo
    # Estabelecimentos (CSV ~8 GB). preserve_insertion_order=false permite
    # streaming do COPY sem manter o arquivo inteiro em memoria.
    con.execute("SET memory_limit='12GB'")
    con.execute("SET threads=4")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET temp_directory='{(STAGING_DIR / 'duckdb_tmp').as_posix()}'")
    ok_todas = True
    for job in jobs:
        ok = converter_tabela(con, job, safra, raw_dir, staging_dir)
        ok_todas = ok_todas and ok
    con.close()

    if not ok_todas:
        print(f"\nSafra {safra}: conversao incompleta, raw/ e staging/ mantidos para investigacao.")
        sys.exit(1)

    shutil.rmtree(staging_dir, ignore_errors=True)
    if manter_raw:
        manifest["status_geral"] = "convertido"
        manifest_path = raw_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nSafra {safra}: convertida com sucesso. raw/ mantido (--manter-raw).")
    else:
        shutil.rmtree(raw_dir)
        print(f"\nSafra {safra}: convertida com sucesso. raw/ e staging/ removidos.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("safra", help="Safra no formato AAAA-MM, ex: 2026-06")
    parser.add_argument("--forcar", action="store_true", help="reconverte mesmo se ja convertida")
    parser.add_argument("--manter-raw", action="store_true", help="nao apaga os zips originais apos converter")
    args = parser.parse_args()

    converter_safra(args.safra, forcar=args.forcar, manter_raw=args.manter_raw)


if __name__ == "__main__":
    main()
