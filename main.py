#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import os
import sys

from rich.console import Console

from src.aggregator import run_aggregations
from src.config import ALL_UFS, PRESET_ELECTIONS, ElectionConfig
from src.worker import process_uf

console = Console()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Coleta e contabiliza em memória todos os votos após as 17h no 2º turno das Eleições Gerais."
    )
    parser.add_argument(
        "--year",
        type=int,
        default=2026,
        choices=sorted(PRESET_ELECTIONS.keys()),
        help="Ano da eleição (padrão: 2026).",
    )
    parser.add_argument(
        "--pleito",
        type=str,
        default=None,
        help="Sobrescreve o código do pleito no TSE (padrão: 3221 para 2026 2º turno).",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Sobrescreve a data do 2º turno no formato DD/MM/YYYY (padrão: 25/10/2026).",
    )
    parser.add_argument(
        "--uf",
        nargs="+",
        default=list(ALL_UFS),
        help="Lista de UFs para processar (ex: --uf AC RR AP). Padrão: todas as 28 UFs (incluindo ZZ).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=48,
        help="Número máximo de conexões HTTP simultâneas no modo API em RAM (padrão: 48).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=max(1, (os.cpu_count() or 4)),
        help="Número de processos paralelos para descompactação de .logjez (padrão: total de CPUs).",
    )
    parser.add_argument(
        "--force-api",
        action="store_true",
        help="Força o download individual de .logjez em memória via API resultados.tse.jus.br.",
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help="Verifica seções ausentes nos Parquets já baixados frente ao cs.json atual e baixa apenas o delta.",
    )
    parser.add_argument(
        "--aggregate-only",
        action="store_true",
        help="Executa apenas a etapa de agregação DuckDB sobre os checkpoints já baixados.",
    )
    return parser.parse_args(argv)


async def async_main(args: argparse.Namespace) -> int:
    base_cfg = PRESET_ELECTIONS[args.year]
    config = ElectionConfig(
        year=base_cfg.year,
        turn=base_cfg.turn,
        pleito_code=args.pleito or base_cfg.pleito_code,
        election_date=args.date or base_cfg.election_date,
        next_day_date=base_cfg.next_day_date,
    )

    ufs = [u.upper() for u in args.uf]
    invalid_ufs = [u for u in ufs if u not in ALL_UFS]
    if invalid_ufs:
        console.print(f"[bold red]UFs inválidas:[/] {invalid_ufs}. Valores aceitos: {ALL_UFS}")
        return 1

    console.print(
        f"[bold blue]Eleições Gerais {config.year} ({config.turn}º Turno)[/] | "
        f"Data: [bold]{config.election_date}[/] | Pleito: [bold]{config.pleito_code}[/] | "
        f"UFs: [bold]{len(ufs)}[/]"
    )

    if not args.aggregate_only:
        for uf in ufs:
            try:
                await process_uf(
                    config=config,
                    uf=uf,
                    concurrency=args.concurrency,
                    cpu_workers=args.workers,
                    force_api=args.force_api,
                    repair_missing=args.repair,
                )
                # Atualiza os arquivos agregados incrementalmente após cada UF concluída
                run_aggregations(config)
            except Exception as exc:
                console.print(f"[bold red]Erro ao processar UF {uf}:[/] {exc}")

    try:
        outputs = run_aggregations(config)
        console.print("\n[bold green]Arquivos finais gerados com sucesso em data/output/:[/]")
        for name, path in outputs.items():
            if name.endswith("_csv"):
                console.print(f"  • {path}")
    except Exception as exc:
        console.print(f"[bold yellow]Aviso na agregação final:[/] {exc}")
        return 1

    return 0


def main() -> None:
    args = parse_args()
    raise SystemExit(asyncio.run(async_main(args)))


if __name__ == "__main__":
    main()
