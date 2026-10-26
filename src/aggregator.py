from __future__ import annotations

from pathlib import Path
import duckdb
from rich.console import Console
from rich.table import Table

from src.config import CHECKPOINT_DIR, OUTPUT_DIR, ElectionConfig

console = Console()


def run_aggregations(config: ElectionConfig) -> dict[str, Path]:
    """
    Lê todos os checkpoints Parquet por UF (`secoes_{year}_{turn}t_*.parquet`) e gera
    os relatórios consolidados (CSV e Parquet) para:
    - Seção (`votos_apos_17h_secao`)
    - Município (`votos_apos_17h_municipio`)
    - UF / Estado (`votos_apos_17h_uf`)
    - Região (`votos_apos_17h_regiao`)
    - Brasil (`votos_apos_17h_brasil`)
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    parquet_glob = (CHECKPOINT_DIR / f"secoes_{config.year}_{config.turn}t_*.parquet").as_posix()
    existing_parquets = list(CHECKPOINT_DIR.glob(f"secoes_{config.year}_{config.turn}t_*.parquet"))

    if not existing_parquets:
        raise FileNotFoundError(
            f"Nenhum arquivo Parquet de checkpoint encontrado em {CHECKPOINT_DIR} "
            f"para a eleição {config.year} ({config.turn}º turno)."
        )

    con = duckdb.connect(":memory:")
    con.execute(
        f"""
        CREATE TABLE raw_secoes AS
        SELECT * FROM read_parquet('{parquet_glob}', union_by_name=true);
        """
    )
    con.execute(
        """
        ALTER TABLE raw_secoes ADD COLUMN IF NOT EXISTS hora_fechamento_urna_brt VARCHAR;
        """
    )
    con.execute(
        """
        CREATE VIEW secoes AS
        SELECT
            sg_uf,
            nm_regiao,
            cd_municipio_tse,
            nm_municipio,
            nr_zona,
            nr_secao,
            CAST(total_votos AS BIGINT) AS total_votos,
            CAST(votos_apos_17h_local AS BIGINT) AS votos_apos_17h_local,
            CAST(votos_apos_17h_brt AS BIGINT) AS votos_apos_17h_brt,
            CAST(hora_fechamento_urna_brt AS VARCHAR) AS hora_fechamento_urna_brt
        FROM raw_secoes;
        """
    )

    outputs: dict[str, Path] = {}

    queries = {
        "secao": """
            SELECT
                sg_uf,
                nm_regiao,
                cd_municipio_tse,
                nm_municipio,
                nr_zona,
                nr_secao,
                total_votos,
                votos_apos_17h_brt,
                CASE
                    WHEN votos_apos_17h_brt > 0 THEN hora_fechamento_urna_brt
                    ELSE NULL
                END AS hora_fechamento_urna_brt
            FROM secoes
            WHERE sg_uf <> 'ZZ'
            ORDER BY sg_uf, cd_municipio_tse, nr_zona, nr_secao
        """,
        "municipio": """
            SELECT
                sg_uf,
                nm_regiao,
                cd_municipio_tse,
                nm_municipio,
                COUNT(*) AS total_urnas_secoes,
                SUM(CASE WHEN votos_apos_17h_brt > 0 THEN 1 ELSE 0 END) AS urnas_secoes_apos_17h_brt,
                ROUND(100.0 * SUM(CASE WHEN votos_apos_17h_brt > 0 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 4) AS pct_urnas_secoes_apos_17h_brt,
                SUM(total_votos) AS total_votos,
                SUM(votos_apos_17h_brt) AS votos_apos_17h_brt,
                ROUND(100.0 * SUM(votos_apos_17h_brt) / NULLIF(SUM(total_votos), 0), 4) AS pct_votos_apos_17h_brt
            FROM secoes
            WHERE sg_uf <> 'ZZ'
            GROUP BY sg_uf, nm_regiao, cd_municipio_tse, nm_municipio
            ORDER BY sg_uf, nm_municipio
        """,
        "uf": """
            SELECT
                sg_uf,
                nm_regiao,
                COUNT(DISTINCT cd_municipio_tse) AS total_municipios,
                COUNT(*) AS total_urnas_secoes,
                SUM(CASE WHEN votos_apos_17h_brt > 0 THEN 1 ELSE 0 END) AS urnas_secoes_apos_17h_brt,
                ROUND(100.0 * SUM(CASE WHEN votos_apos_17h_brt > 0 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 4) AS pct_urnas_secoes_apos_17h_brt,
                SUM(total_votos) AS total_votos,
                SUM(votos_apos_17h_brt) AS votos_apos_17h_brt,
                ROUND(100.0 * SUM(votos_apos_17h_brt) / NULLIF(SUM(total_votos), 0), 4) AS pct_votos_apos_17h_brt
            FROM secoes
            WHERE sg_uf <> 'ZZ'
            GROUP BY sg_uf, nm_regiao
            ORDER BY sg_uf
        """,
        "regiao": """
            SELECT
                nm_regiao,
                COUNT(DISTINCT sg_uf) AS total_ufs,
                COUNT(DISTINCT cd_municipio_tse) AS total_municipios,
                COUNT(*) AS total_urnas_secoes,
                SUM(CASE WHEN votos_apos_17h_brt > 0 THEN 1 ELSE 0 END) AS urnas_secoes_apos_17h_brt,
                ROUND(100.0 * SUM(CASE WHEN votos_apos_17h_brt > 0 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 4) AS pct_urnas_secoes_apos_17h_brt,
                SUM(total_votos) AS total_votos,
                SUM(votos_apos_17h_brt) AS votos_apos_17h_brt,
                ROUND(100.0 * SUM(votos_apos_17h_brt) / NULLIF(SUM(total_votos), 0), 4) AS pct_votos_apos_17h_brt
            FROM secoes
            WHERE sg_uf <> 'ZZ'
            GROUP BY nm_regiao
            ORDER BY nm_regiao
        """,
        "brasil": """
            SELECT
                'BRASIL' AS escopo,
                COUNT(DISTINCT sg_uf) AS total_ufs,
                COUNT(DISTINCT cd_municipio_tse) AS total_municipios,
                COUNT(*) AS total_urnas_secoes,
                SUM(CASE WHEN votos_apos_17h_brt > 0 THEN 1 ELSE 0 END) AS urnas_secoes_apos_17h_brt,
                ROUND(100.0 * SUM(CASE WHEN votos_apos_17h_brt > 0 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 4) AS pct_urnas_secoes_apos_17h_brt,
                SUM(total_votos) AS total_votos,
                SUM(votos_apos_17h_brt) AS votos_apos_17h_brt,
                ROUND(100.0 * SUM(votos_apos_17h_brt) / NULLIF(SUM(total_votos), 0), 4) AS pct_votos_apos_17h_brt
            FROM secoes
            WHERE sg_uf <> 'ZZ'
        """,
    }

    for level, sql in queries.items():
        csv_path = OUTPUT_DIR / f"votos_apos_17h_{level}.csv"
        pq_path = OUTPUT_DIR / f"votos_apos_17h_{level}.parquet"
        con.execute(f"COPY ({sql}) TO '{csv_path.as_posix()}' (HEADER, DELIMITER ',');")
        con.execute(f"COPY ({sql}) TO '{pq_path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD);")
        outputs[f"{level}_csv"] = csv_path
        outputs[f"{level}_parquet"] = pq_path

    # Exibe tabela resumo por Região e Total Brasil no terminal (apenas 17h BRT, sem ZZ)
    regiao_rows = con.execute(queries["regiao"]).fetchall()
    br_row = con.execute(queries["brasil"]).fetchone()
    con.close()

    table = Table(title=f"Resumo de Votos e Urnas/Seções Após as 17h BRT ({config.year} - {config.turn}º Turno)")
    table.add_column("Região / Escopo", style="bold cyan")
    table.add_column("Urnas/Seções", justify="right")
    table.add_column("Urnas >17h BRT", justify="right", style="green")
    table.add_column("% Urnas", justify="right")
    table.add_column("Total Votos", justify="right")
    table.add_column("Votos >17h BRT", justify="right", style="green")
    table.add_column("% Votos BRT", justify="right")

    for r in regiao_rows:
        (
            nm_reg,
            _,
            _,
            tot_sec,
            sec_brt,
            pct_sec_brt,
            tot_v,
            v_brt,
            pct_brt,
        ) = r
        table.add_row(
            str(nm_reg),
            f"{tot_sec or 0:,}",
            f"{sec_brt or 0:,}",
            f"{pct_sec_brt or 0.0:.2f}%",
            f"{tot_v or 0:,}",
            f"{v_brt or 0:,}",
            f"{pct_brt or 0.0:.4f}%",
        )

    if br_row:
        (
            _,
            _,
            _,
            tot_sec,
            sec_brt,
            pct_sec_brt,
            tot_v,
            v_brt,
            pct_brt,
        ) = br_row
        table.add_section()
        table.add_row(
            "TOTAL BRASIL",
            f"{tot_sec or 0:,}",
            f"{sec_brt or 0:,}",
            f"{pct_sec_brt or 0.0:.2f}%",
            f"{tot_v or 0:,}",
            f"{v_brt or 0:,}",
            f"{pct_brt or 0.0:.4f}%",
            style="bold magenta",
        )

    console.print(table)
    return outputs
