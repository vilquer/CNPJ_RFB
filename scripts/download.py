"""
Baixa os arquivos de uma safra (mes) dos dados abertos de CNPJ da RFB
via WebDAV publico do Nextcloud, de forma idempotente.

Uso:
    python download.py 2026-06
    python download.py 2026-06 --forcar        # rebaixa mesmo se ja completo
    python download.py 2026-06 --so-listar      # so mostra o que existe remotamente

O manifest.json (em raw/{safra}/manifest.json) guarda o estado de cada
arquivo. Um arquivo so e considerado baixado se o tamanho local bate com
o tamanho remoto reportado pelo PROPFIND.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests
from tqdm import tqdm

SHARE_TOKEN = "YggdBLfdninEJX9"
WEBDAV_BASE = "https://arquivos.receitafederal.gov.br/public.php/webdav"
RAW_DIR = Path(__file__).resolve().parent.parent / "raw"

HREF_RE = re.compile(r"<d:href>(.*?)</d:href>", re.IGNORECASE)
SIZE_RE = re.compile(r"<d:getcontentlength>(\d+)</d:getcontentlength>", re.IGNORECASE)
COLLECTION_RE = re.compile(r"<d:resourcetype>\s*<d:collection", re.IGNORECASE)


def listar_remoto(safra: str) -> list[dict]:
    """Lista arquivos (nao-diretorios) disponiveis para a safra via PROPFIND."""
    url = f"{WEBDAV_BASE}/{safra}/"
    resp = requests.request(
        "PROPFIND",
        url,
        auth=(SHARE_TOKEN, ""),
        headers={"Depth": "1"},
        timeout=30,
    )
    resp.raise_for_status()

    # Parse simplificado: cada <d:response> vira um bloco; extrai href, size
    # e se e diretorio, sem depender de biblioteca XML pesada.
    blocos = resp.text.split("<d:response>")[1:]
    arquivos = []
    for bloco in blocos:
        href_match = HREF_RE.search(bloco)
        if not href_match:
            continue
        href = href_match.group(1)
        nome = href.rstrip("/").split("/")[-1]
        if not nome:
            continue
        if COLLECTION_RE.search(bloco):
            continue  # e uma pasta, pula
        size_match = SIZE_RE.search(bloco)
        tamanho = int(size_match.group(1)) if size_match else None
        arquivos.append({"nome": nome, "tamanho_remoto": tamanho})
    return arquivos


def carregar_manifest(safra_dir: Path) -> dict:
    manifest_path = safra_dir / "manifest.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    return {"safra": safra_dir.name, "arquivos": {}}


def salvar_manifest(safra_dir: Path, manifest: dict) -> None:
    manifest_path = safra_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def arquivo_ja_baixado(local_path: Path, tamanho_remoto: int | None) -> bool:
    if not local_path.exists():
        return False
    if tamanho_remoto is None:
        return True  # sem tamanho remoto pra comparar, confia na existencia
    return local_path.stat().st_size == tamanho_remoto


def baixar_arquivo(
    safra: str, nome: str, destino: Path, tamanho_remoto: int | None, tentativas: int = 3
) -> None:
    """Baixa com retry: o servidor da RFB derruba conexoes longas ocasionalmente."""
    url = f"{WEBDAV_BASE}/{safra}/{nome}"
    for tentativa in range(1, tentativas + 1):
        try:
            with requests.get(url, auth=(SHARE_TOKEN, ""), stream=True, timeout=60) as resp:
                resp.raise_for_status()
                total = tamanho_remoto or int(resp.headers.get("Content-Length", 0)) or None
                with open(destino, "wb") as f, tqdm(
                    total=total,
                    unit="B",
                    unit_scale=True,
                    unit_divisor=1024,
                    desc=f"  {nome}",
                    leave=False,
                ) as barra:
                    for chunk in resp.iter_content(chunk_size=1024 * 1024):
                        f.write(chunk)
                        barra.update(len(chunk))
            return
        except requests.RequestException:
            if tentativa == tentativas:
                raise
            espera = 5 * tentativa
            print(f"  {nome}: conexao caiu (tentativa {tentativa}/{tentativas}), aguardando {espera}s...")
            time.sleep(espera)


def baixar_safra(safra: str, forcar: bool = False) -> None:
    safra_dir = RAW_DIR / safra
    safra_dir.mkdir(parents=True, exist_ok=True)

    remoto = listar_remoto(safra)
    if not remoto:
        print(f"Nenhum arquivo encontrado para a safra {safra}.")
        sys.exit(1)

    manifest = carregar_manifest(safra_dir)

    total = len(remoto)
    for i, item in enumerate(remoto, start=1):
        nome = item["nome"]
        tamanho_remoto = item["tamanho_remoto"]
        destino = safra_dir / nome

        # Tamanho local == remoto e prova suficiente de download completo;
        # nao exige entrada previa no manifest (arquivo pode ter vindo de fora).
        if (not forcar) and arquivo_ja_baixado(destino, tamanho_remoto):
            manifest["arquivos"][nome] = {"status": "baixado", "tamanho": tamanho_remoto}
            print(f"[{i}/{total}] {nome}: ja baixado, pulando.")
            continue

        tamanho_mb = (tamanho_remoto or 0) / 1024 / 1024
        print(f"[{i}/{total}] {nome}: baixando ({tamanho_mb:.1f} MB)...")
        try:
            baixar_arquivo(safra, nome, destino, tamanho_remoto)
        except requests.RequestException as e:
            manifest["arquivos"][nome] = {"status": "erro", "erro": str(e)}
            salvar_manifest(safra_dir, manifest)
            print(f"  ERRO ao baixar {nome}: {e}")
            continue

        if not arquivo_ja_baixado(destino, tamanho_remoto):
            manifest["arquivos"][nome] = {
                "status": "erro",
                "erro": "tamanho local nao bate com o remoto apos download",
            }
            salvar_manifest(safra_dir, manifest)
            print(f"  AVISO: tamanho de {nome} nao confere apos download.")
            continue

        manifest["arquivos"][nome] = {
            "status": "baixado",
            "tamanho": tamanho_remoto,
        }
        salvar_manifest(safra_dir, manifest)

    erros = [n for n, v in manifest["arquivos"].items() if v.get("status") == "erro"]
    if erros:
        print(f"\nSafra {safra}: concluida com erros em {len(erros)} arquivo(s): {erros}")
        sys.exit(1)
    else:
        manifest["status_geral"] = "baixado"
        salvar_manifest(safra_dir, manifest)
        print(f"\nSafra {safra}: todos os {total} arquivos baixados com sucesso em {safra_dir}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("safra", help="Safra no formato AAAA-MM, ex: 2026-06")
    parser.add_argument("--forcar", action="store_true", help="rebaixa mesmo se ja completo")
    parser.add_argument("--so-listar", action="store_true", help="so lista o que existe remotamente, nao baixa")
    args = parser.parse_args()

    if args.so_listar:
        for item in listar_remoto(args.safra):
            tamanho_mb = (item["tamanho_remoto"] or 0) / 1024 / 1024
            print(f"{item['nome']:30s} {tamanho_mb:8.1f} MB")
        return

    baixar_safra(args.safra, forcar=args.forcar)


if __name__ == "__main__":
    main()
