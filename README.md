# Receita Federal CNPJ — Pipeline de Ingestão e Consulta

Pipeline local para baixar, converter e consultar os
[dados abertos de CNPJ](https://arquivos.receitafederal.gov.br/index.php/s/YggdBLfdninEJX9)
da Receita Federal do Brasil (RFB): Empresas, Estabelecimentos, Sócios,
Simples/MEI e tabelas de domínio.

Os CSVs mensais (~7 GB compactados, ~218 milhões de linhas) viram **Parquet
particionado** convertido via **DuckDB**, e uma camada de consulta pronta
(`rfb.duckdb`) oferece views enriquecidas e macros de busca — tudo local,
sem servidor.

## Requisitos

- Python 3.10+
- ~40 GB de disco livre durante a conversão (~8 GB de pico de staging + 8,3 GB de Parquet final)
- 16 GB+ de RAM recomendado (DuckDB limitado a 12 GB no script)

```bash
pip install requests tqdm duckdb
```

## Uso

Ciclo completo de uma safra (mês):

```bash
python scripts/download.py 2026-06     # baixa os 37 zips via WebDAV (~7,1 GB)
python scripts/convert.py 2026-06      # extrai + converte pra Parquet particionado
python scripts/criar_views.py          # cria/atualiza rfb.duckdb apontando pra safra
```

Os três scripts são idempotentes: podem ser interrompidos e relançados que
retomam de onde pararam (download pula arquivos completos, conversão pula
partes já convertidas).

### Consultando

```python
import duckdb
con = duckdb.connect('rfb.duckdb', read_only=True)

# Ficha completa por CNPJ (com ou sem pontuação; 14 dígitos ou 8 do básico)
con.sql("SELECT * FROM ficha_cnpj('00.000.000/0001-91')").show()

# Quadro societário
con.sql("SELECT * FROM socios_cnpj('00000000')").show()

# Busca por razão social / nome fantasia
con.sql("SELECT * FROM busca_nome('BANCO DO BRASIL') LIMIT 10").show()

# Análises direto nas views enriquecidas
con.sql("""
    SELECT uf, count(*) AS ativas
    FROM estabelecimentos_completos
    WHERE situacao = 'ativa'
    GROUP BY uf ORDER BY ativas DESC
""").show()
```

| Objeto | Descrição |
|---|---|
| `ficha_cnpj(cnpj)` | Ficha do estabelecimento: razão social, CNAE descrito, endereço, situação |
| `socios_cnpj(cnpj)` | Sócios com qualificação e faixa etária decodificadas |
| `busca_nome(termo)` | Busca em razão social e nome fantasia |
| `estabelecimentos_completos` | 71,9M estabelecimentos com joins de domínio resolvidos |
| `empresas_completas` | 68,6M empresas com natureza jurídica, porte, flags Simples/MEI |
| `socios_completos` | 27,8M vínculos societários enriquecidos |
| views base | `empresas`, `estabelecimentos`, `socios`, `simples`, `cnaes`, `motivos`, `municipios`, `naturezas`, `paises`, `qualificacoes` |

## App (Streamlit)

Interface local de consulta e dashboards sobre o `rfb.duckdb`:

```bash
pip install -r requirements.txt
streamlit run app/Home.py
```

- **Home**: panorama Brasil (tiles, situação cadastral, ativos por UF, top CNAEs)
- **Consulta CNPJ**: ficha completa por CNPJ (14 ou 8 dígitos, com/sem pontuação)
  ou busca por nome — quadro societário e demais estabelecimentos da empresa
- **Recorte UF**: drill-down UF → região geográfica intermediária (IBGE) → município
- **Dinâmica empresarial**: aberturas por ano, sobrevivência (idade na baixa)
  e longevidade das ativas, com filtro por UF

O mapeamento município→região vem de `apoio/ibge_regioes_br.csv` (gerado por
`scripts/baixar_regioes_ibge.py` a partir da API de localidades do IBGE, com
aliases para grafias divergentes da RFB — ex.: PARATI→Paraty).

## Estrutura

```
├── scripts/
│   ├── download.py        # WebDAV da RFB -> raw/{safra}/ (retry + barra de progresso)
│   ├── convert.py         # zips -> parquet/tabela=X/safra=Y/ via DuckDB
│   ├── criar_views.py     # cria/atualiza rfb.duckdb (views + macros)
│   └── *.json             # schemas de coluna por tabela (layout oficial da RFB)
├── app/                   # app Streamlit (Home + 3 páginas, lib de queries cacheadas)
├── apoio/
│   └── ibge_regioes_br.csv        # município -> regiões IBGE (27 UFs + aliases RFB)
├── notebooks/
│   ├── analise_exploratoria.ipynb  # EDA: situação, UF, CNAEs, aberturas/ano, porte, sócios
│   └── analise_rs.ipynb            # recorte RS: regiões IBGE, sobrevivência, longevidade
├── parquet/               # dado final particionado (gerado)
├── rfb.duckdb             # camada de consulta (gerado)
└── CLAUDE.md              # plano/decisões do projeto (fonte de verdade)
```

## Detalhes de implementação

- **DuckDB, não pandas**: Estabelecimentos tem 71,9M de linhas; DuckDB converte
  CSV→Parquet em streaming com `memory_limit` fixado, sem estourar RAM.
- **Encoding**: os CSVs da RFB são cp1252 com bytes de lixo raros (0x80–0x9F);
  o convert.py filtra esses bytes na extração e lê com `latin-1` nativo
  (encodings ICU do DuckDB 1.5 decodificam errado — ver CLAUDE.md).
- **CPF mascarado na origem**: campos de CPF de sócios já vêm anonimizados
  pela própria RFB (`***240659**`) por força do art. 129 §2º da Lei 13.473/2017.
- **Particionamento por safra**: `parquet/tabela=X/safra=AAAA-MM/` permite
  acumular meses sem reprocessar; as views apontam sempre pra safra mais recente.
- Layout oficial das colunas: [cnpj-metadados.pdf](https://www.gov.br/receitafederal/dados/cnpj-metadados.pdf)

## Licença

[MIT](LICENSE) — o código. Os dados de CNPJ são públicos, publicados pela
Receita Federal do Brasil; observe as condições de uso da fonte.
