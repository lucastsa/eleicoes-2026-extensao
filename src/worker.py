from __future__ import annotations

import asyncio
from concurrent.futures import ProcessPoolExecutor
import csv
from pathlib import Path
import zipfile

import duckdb
import httpx
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

from src.config import CHECKPOINT_DIR, TMP_DIR, UF_TO_REGIAO, ElectionConfig
from src.metadata import SectionMeta, fetch_uf_sections_and_municipios
from src.parser import (
    SectionVoteResult,
    parse_ids_from_filename,
    process_logjez_bytes,
    process_multiple_logjez_bytes,
)

console = Console()

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "application/json, application/octet-stream, */*",
}


def get_uf_checkpoint_parquet(config: ElectionConfig, uf: str) -> Path:
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    return CHECKPOINT_DIR / f"secoes_{config.year}_{config.turn}t_{uf.upper()}.parquet"


def get_uf_partial_csv(config: ElectionConfig, uf: str) -> Path:
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    return CHECKPOINT_DIR / f"partial_{config.year}_{config.turn}t_{uf.upper()}.csv"


def load_processed_section_keys(partial_csv: Path) -> set[tuple[str, str, str]]:
    """Carrega chaves (cd_municipio_tse, nr_zona, nr_secao) já processadas no arquivo parcial."""
    done: set[tuple[str, str, str]] = set()
    if not partial_csv.exists():
        return done
    with partial_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            done.add((row["cd_municipio_tse"], row["nr_zona"], row["nr_secao"]))
    return done


def append_results_to_partial_csv(partial_csv: Path, results: list[SectionVoteResult]) -> None:
    if not results:
        return
    file_exists = partial_csv.exists() and partial_csv.stat().st_size > 0
    with partial_csv.open("a", encoding="utf-8", newline="") as f:
        fieldnames = [
            "sg_uf",
            "nm_regiao",
            "cd_municipio_tse",
            "nm_municipio",
            "nr_zona",
            "nr_secao",
            "total_votos",
            "votos_apos_17h_local",
            "votos_apos_17h_brt",
            "hora_fechamento_urna_brt",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for r in results:
            writer.writerow(
                {
                    "sg_uf": r.sg_uf,
                    "nm_regiao": r.nm_regiao,
                    "cd_municipio_tse": r.cd_municipio_tse,
                    "nm_municipio": r.nm_municipio,
                    "nr_zona": r.nr_zona,
                    "nr_secao": r.nr_secao,
                    "total_votos": r.total_votos,
                    "votos_apos_17h_local": r.votos_apos_17h_local,
                    "votos_apos_17h_brt": r.votos_apos_17h_brt,
                    "hora_fechamento_urna_brt": r.hora_fechamento_urna_brt or "",
                }
            )


def finalize_uf_parquet(partial_csv: Path, final_parquet: Path) -> None:
    """Converte o CSV parcial da UF em um arquivo Parquet deduplicado e remove o CSV temporário."""
    con = duckdb.connect(":memory:")
    con.execute(
        f"""
        COPY (
            SELECT DISTINCT ON (sg_uf, cd_municipio_tse, nr_zona, nr_secao)
                sg_uf,
                nm_regiao,
                LPAD(CAST(cd_municipio_tse AS VARCHAR), 5, '0') AS cd_municipio_tse,
                nm_municipio,
                LPAD(CAST(nr_zona AS VARCHAR), 4, '0') AS nr_zona,
                LPAD(CAST(nr_secao AS VARCHAR), 4, '0') AS nr_secao,
                CAST(total_votos AS BIGINT) AS total_votos,
                CAST(votos_apos_17h_local AS BIGINT) AS votos_apos_17h_local,
                CAST(votos_apos_17h_brt AS BIGINT) AS votos_apos_17h_brt,
                NULLIF(CAST(hora_fechamento_urna_brt AS VARCHAR), '') AS hora_fechamento_urna_brt
            FROM read_csv_auto('{partial_csv.as_posix()}', all_varchar=true)
            ORDER BY sg_uf, cd_municipio_tse, nr_zona, nr_secao
        ) TO '{final_parquet.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD);
        """
    )
    con.close()
    partial_csv.unlink(missing_ok=True)


async def check_cdn_zip_available(client: httpx.AsyncClient, url: str) -> int | None:
    """Verifica se o arquivo .zip consolidado da UF está disponível no CDN e retorna seu tamanho em bytes."""
    try:
        resp = await client.head(url, timeout=15.0, follow_redirects=True)
        if resp.status_code == 200:
            cl = resp.headers.get("content-length")
            return int(cl) if cl and cl.isdigit() else 0
    except Exception:
        pass
    return None


async def download_cdn_zip_temporarily(
    client: httpx.AsyncClient,
    url: str,
    dest_path: Path,
    uf: str,
) -> Path:
    """Baixa o pacote .zip da UF com suporte a retomada (HTTP Range) para processamento temporário."""
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    existing_size = dest_path.stat().st_size if dest_path.exists() else 0
    headers = dict(DEFAULT_HEADERS)
    if existing_size > 0:
        headers["Range"] = f"bytes={existing_size}-"

    async with client.stream("GET", url, headers=headers, timeout=60.0, follow_redirects=True) as resp:
        if resp.status_code == 416:
            # Arquivo já foi completamente baixado
            return dest_path
        resp.raise_for_status()
        mode = "ab" if resp.status_code == 206 else "wb"
        if mode == "wb":
            existing_size = 0
        total_len = int(resp.headers.get("content-length", 0)) + existing_size

        with Progress(
            SpinnerColumn(),
            TextColumn(f"[bold cyan]Baixando ZIP temporário {uf}[/]"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task_id = progress.add_task("download", total=total_len or None, completed=existing_size)
            with dest_path.open(mode) as f:
                async for chunk in resp.aiter_bytes(chunk_size=1024 * 256):
                    f.write(chunk)
                    progress.update(task_id, advance=len(chunk))

    return dest_path


def process_uf_from_cdn_zip(
    zip_path: Path,
    uf: str,
    mun_map: dict[str, str],
    config: ElectionConfig,
    partial_csv: Path,
    max_workers: int = 4,
) -> None:
    """
    Lê apenas os arquivos *.logjez de dentro do .zip da UF em streaming (sem extrair .bu/.rdv no disco),
    contabiliza os votos em memória usando múltiplos núcleos e salva o resultado parcial.
    """
    done_keys = load_processed_section_keys(partial_csv)
    batch_results: list[SectionVoteResult] = []

    with zipfile.ZipFile(zip_path, "r") as zf:
        logjez_members = [
            name for name in zf.namelist()
            if name.lower().endswith((".logjez", ".jez"))
        ]

        with Progress(
            SpinnerColumn(),
            TextColumn(f"[bold green]Processando {uf} (ZIP em memória)[/]"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task_id = progress.add_task("parse_zip", total=len(logjez_members))

            with ProcessPoolExecutor(max_workers=max_workers) as pool:
                pending_futures = []

                for member_name in logjez_members:
                    ids = parse_ids_from_filename(member_name)
                    if not ids:
                        progress.update(task_id, advance=1)
                        continue
                    cd_mun, nr_zona, nr_secao = ids
                    if (cd_mun, nr_zona, nr_secao) in done_keys:
                        progress.update(task_id, advance=1)
                        continue

                    raw_bytes = zf.read(member_name)
                    nm_mun = mun_map.get(cd_mun, f"MUNICIPIO_{cd_mun}")
                    fut = pool.submit(
                        process_logjez_bytes,
                        raw_bytes,
                        uf,
                        cd_mun,
                        nm_mun,
                        nr_zona,
                        nr_secao,
                        config.election_date,
                        config.next_day_date,
                    )
                    pending_futures.append(fut)

                    if len(pending_futures) >= max_workers * 8:
                        for completed_fut in pending_futures:
                            batch_results.append(completed_fut.result())
                            progress.update(task_id, advance=1)
                        pending_futures.clear()

                        if len(batch_results) >= 500:
                            append_results_to_partial_csv(partial_csv, batch_results)
                            batch_results.clear()

                for completed_fut in pending_futures:
                    batch_results.append(completed_fut.result())
                    progress.update(task_id, advance=1)
                pending_futures.clear()

    if batch_results:
        append_results_to_partial_csv(partial_csv, batch_results)


async def fetch_and_process_single_section_api(
    client: httpx.AsyncClient,
    config: ElectionConfig,
    p_tag: str,
    sec: SectionMeta,
    semaphore: asyncio.Semaphore,
) -> SectionVoteResult | None:
    """
    Baixa o aux.json e o .logjez de uma seção diretamente em memória RAM a partir da API
    resultados.tse.jus.br, extrai e conta os votos após 17h e descarta os bytes brutos.
    """
    uf_low = sec.sg_uf.lower()
    m = sec.cd_municipio_tse
    z = sec.nr_zona
    s = sec.nr_secao

    aux_url = (
        f"https://resultados.tse.jus.br/oficial/ele{config.year}/arquivo-urna/{config.pleito_code}"
        f"/dados/{uf_low}/{m}/{z}/{s}/{p_tag}-{uf_low}-m{m}-z{z}-s{s}-aux.json"
    )

    async with semaphore:
        for attempt in range(4):
            try:
                aux_resp = await client.get(aux_url)
                if aux_resp.status_code == 404:
                    return None
                aux_resp.raise_for_status()
                aux_data = aux_resp.json()

                hashes = aux_data.get("hashes") or []
                if not hashes:
                    return None

                # Coleta TODOS os pares (hash, nome_arquivo_log) listados em hashes[]
                # (cobre seções com substituição de urna que possuem mais de um pacote de log)
                log_targets: list[tuple[str, str]] = []
                for h_entry in hashes:
                    h_val = h_entry.get("hash")
                    if not h_val:
                        continue
                    found_in_entry = False
                    # Formato 2026: "arq": [{"nm": "o03221rr0312300070001-log.jez", "tp": "log"}, ...]
                    for arq_obj in h_entry.get("arq", []):
                        nm = arq_obj.get("nm", "") if isinstance(arq_obj, dict) else str(arq_obj)
                        tp = arq_obj.get("tp", "") if isinstance(arq_obj, dict) else ""
                        if tp == "log" or nm.lower().endswith((".logjez", ".jez")):
                            log_targets.append((h_val, nm))
                            found_in_entry = True
                    # Formato 2022: "nmarq": ["o00407-0312300070001.logjez", ...]
                    if not found_in_entry:
                        for fname in h_entry.get("nmarq", []):
                            if fname.lower().endswith((".logjez", ".jez")):
                                log_targets.append((h_val, fname))
                                found_in_entry = True

                if not log_targets:
                    first_hash = hashes[0].get("hash")
                    if not first_hash:
                        return None
                    log_targets.append((first_hash, f"o{config.pleito_pad5}{uf_low}{m}{z}{s}-log.jez"))

                raw_bytes_list: list[bytes] = []
                for sec_hash, logjez_fname in log_targets:
                    log_url = config.section_logjez_url(
                        uf=sec.sg_uf,
                        cd_municipio=m,
                        nr_zona=z,
                        nr_secao=s,
                        sec_hash=sec_hash,
                        filename=logjez_fname,
                    )
                    log_resp = await client.get(log_url)
                    if log_resp.status_code == 404:
                        continue
                    log_resp.raise_for_status()
                    if log_resp.content:
                        raw_bytes_list.append(log_resp.content)

                if not raw_bytes_list:
                    return None

                if all(b[:4] == b"PK\x03\x04" for b in raw_bytes_list):
                    return process_multiple_logjez_bytes(
                        raw_bytes_list,
                        sec.sg_uf,
                        m,
                        sec.nm_municipio,
                        z,
                        s,
                        config.election_date,
                        config.next_day_date,
                    )
                return await asyncio.to_thread(
                    process_multiple_logjez_bytes,
                    raw_bytes_list,
                    sec.sg_uf,
                    m,
                    sec.nm_municipio,
                    z,
                    s,
                    config.election_date,
                    config.next_day_date,
                )
            except Exception:
                if attempt == 3:
                    return None
                await asyncio.sleep(0.4 * (1.8**attempt))
    return None


async def process_uf_via_api(
    client: httpx.AsyncClient,
    config: ElectionConfig,
    uf: str,
    sections: list[SectionMeta],
    p_tag: str,
    partial_csv: Path,
    concurrency: int = 48,
) -> None:
    """
    Processa todas as seções de uma UF via API (100% em RAM, sem salvar arquivos de urna em disco)
    usando uma fila contínua de workers assíncronos com timeout rígido por seção.
    """
    done_keys = load_processed_section_keys(partial_csv)
    remaining = [
        sec for sec in sections
        if (sec.cd_municipio_tse, sec.nr_zona, sec.nr_secao) not in done_keys
    ]

    total_sections = len(sections)
    completed_count = total_sections - len(remaining)
    if not remaining:
        return

    console.print(
        f"[cyan][{uf}][/] Iniciando API em RAM: {len(remaining):,} seções restantes "
        f"(já salvas no checkpoint parcial: {completed_count:,}/{total_sections:,})"
    )

    queue: asyncio.Queue[SectionMeta | None] = asyncio.Queue()
    for sec in remaining:
        queue.put_nowait(sec)
    for _ in range(concurrency):
        queue.put_nowait(None)

    semaphore = asyncio.Semaphore(concurrency)
    buffer: list[SectionVoteResult] = []
    flush_lock = asyncio.Lock()

    async def worker() -> None:
        nonlocal completed_count
        while True:
            sec = await queue.get()
            if sec is None:
                queue.task_done()
                break
            try:
                res = await asyncio.wait_for(
                    fetch_and_process_single_section_api(
                        client, config, p_tag, sec, semaphore
                    ),
                    timeout=50.0,
                )
            except Exception:
                res = None

            async with flush_lock:
                completed_count += 1
                if res is not None:
                    buffer.append(res)
                if len(buffer) >= 250:
                    append_results_to_partial_csv(partial_csv, buffer)
                    buffer.clear()
                if completed_count % 1000 == 0 or completed_count == total_sections:
                    console.print(
                        f"[dim][{uf}] Progresso: {completed_count:,}/{total_sections:,} seções "
                        f"({100.0 * completed_count / total_sections:.1f}%)[/]"
                    )
            queue.task_done()

    workers = [asyncio.create_task(worker()) for _ in range(concurrency)]
    await asyncio.gather(*workers)

    if buffer:
        append_results_to_partial_csv(partial_csv, buffer)
        buffer.clear()


def load_parquet_section_keys(parquet_path: Path) -> set[tuple[str, str, str]]:
    """Retorna o conjunto de chaves (cd_municipio_tse, nr_zona, nr_secao) já salvas no Parquet da UF."""
    if not parquet_path.exists():
        return set()
    con = duckdb.connect(":memory:")
    rows = con.execute(
        f"""
        SELECT cd_municipio_tse, nr_zona, nr_secao
        FROM read_parquet('{parquet_path.as_posix()}')
        WHERE total_votos > 0
        """
    ).fetchall()
    con.close()
    return {(str(r[0]).zfill(5), str(r[1]).zfill(4), str(r[2]).zfill(4)) for r in rows}


def merge_partial_csv_into_parquet(partial_csv: Path, final_parquet: Path) -> None:
    """Mescla novas seções recuperadas no CSV parcial com o Parquet existente da UF."""
    if not partial_csv.exists():
        return
    tmp_merged = final_parquet.with_suffix(".merged.parquet")
    con = duckdb.connect(":memory:")
    if final_parquet.exists():
        con.execute(
            f"""
            CREATE TABLE existing_pq AS
            SELECT * FROM read_parquet('{final_parquet.as_posix()}');
            ALTER TABLE existing_pq ADD COLUMN IF NOT EXISTS hora_fechamento_urna_brt VARCHAR;
            """
        )
        con.execute(
            f"""
            CREATE TABLE incoming_csv AS
            SELECT * FROM read_csv_auto('{partial_csv.as_posix()}', all_varchar=true);
            ALTER TABLE incoming_csv ADD COLUMN IF NOT EXISTS hora_fechamento_urna_brt VARCHAR;
            """
        )
        con.execute(
            f"""
            COPY (
                SELECT DISTINCT ON (sg_uf, cd_municipio_tse, nr_zona, nr_secao)
                    sg_uf,
                    nm_regiao,
                    LPAD(CAST(cd_municipio_tse AS VARCHAR), 5, '0') AS cd_municipio_tse,
                    nm_municipio,
                    LPAD(CAST(nr_zona AS VARCHAR), 4, '0') AS nr_zona,
                    LPAD(CAST(nr_secao AS VARCHAR), 4, '0') AS nr_secao,
                    CAST(total_votos AS BIGINT) AS total_votos,
                    CAST(votos_apos_17h_local AS BIGINT) AS votos_apos_17h_local,
                    CAST(votos_apos_17h_brt AS BIGINT) AS votos_apos_17h_brt,
                    hora_fechamento_urna_brt
                FROM (
                    SELECT
                        sg_uf,
                        nm_regiao,
                        cd_municipio_tse,
                        nm_municipio,
                        nr_zona,
                        nr_secao,
                        total_votos,
                        votos_apos_17h_local,
                        votos_apos_17h_brt,
                        NULLIF(CAST(hora_fechamento_urna_brt AS VARCHAR), '') AS hora_fechamento_urna_brt,
                        1 AS priority
                    FROM incoming_csv
                    UNION ALL
                    SELECT
                        sg_uf,
                        nm_regiao,
                        cd_municipio_tse,
                        nm_municipio,
                        nr_zona,
                        nr_secao,
                        total_votos,
                        votos_apos_17h_local,
                        votos_apos_17h_brt,
                        NULLIF(CAST(hora_fechamento_urna_brt AS VARCHAR), '') AS hora_fechamento_urna_brt,
                        2 AS priority
                    FROM existing_pq
                )
                ORDER BY sg_uf, cd_municipio_tse, nr_zona, nr_secao, priority ASC, total_votos DESC
            ) TO '{tmp_merged.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD);
            """
        )
        con.close()
        tmp_merged.replace(final_parquet)
        partial_csv.unlink(missing_ok=True)
    else:
        con.close()
        finalize_uf_parquet(partial_csv, final_parquet)


async def enrich_uf_closing_times(
    config: ElectionConfig,
    uf: str,
    concurrency: int = 64,
) -> Path:
    """
    Re-consulta apenas as seções de uma UF que tiveram votos após as 17h BRT (`votos_apos_17h_brt > 0`)
    e cujo campo `hora_fechamento_urna_brt` ainda não foi preenchido no Parquet da UF.
    """
    uf_up = uf.upper()
    final_parquet = get_uf_checkpoint_parquet(config, uf_up)
    if not final_parquet.exists():
        console.print(f"[yellow]Parquet {final_parquet.name} não encontrado para {uf_up}.[/]")
        return final_parquet

    con = duckdb.connect(":memory:")
    con.execute(
        f"""
        CREATE TABLE pq_sec AS
        SELECT * FROM read_parquet('{final_parquet.as_posix()}');
        ALTER TABLE pq_sec ADD COLUMN IF NOT EXISTS hora_fechamento_urna_brt VARCHAR;
        """
    )
    rows = con.execute(
        """
        SELECT sg_uf, cd_municipio_tse, nm_municipio, nr_zona, nr_secao
        FROM pq_sec
        WHERE votos_apos_17h_brt > 0
          AND (hora_fechamento_urna_brt IS NULL OR hora_fechamento_urna_brt = '')
        ORDER BY cd_municipio_tse, nr_zona, nr_secao
        """
    ).fetchall()
    con.close()

    if not rows:
        console.print(
            f"[dim]✔ UF {uf_up}: todas as seções com votos >17h BRT já possuem hora de fechamento.[/]"
        )
        return final_parquet

    target_sections = [
        SectionMeta(
            sg_uf=str(r[0]),
            cd_municipio_tse=str(r[1]).zfill(5),
            nm_municipio=str(r[2]),
            nr_zona=str(r[3]).zfill(4),
            nr_secao=str(r[4]).zfill(4),
        )
        for r in rows
    ]

    partial_csv = get_uf_partial_csv(config, uf_up)
    p_tag = f"p{config.pleito_pad6}"

    limits = httpx.Limits(
        max_connections=concurrency + 16,
        max_keepalive_connections=concurrency,
        keepalive_expiry=20.0,
    )
    timeout = httpx.Timeout(connect=10.0, read=25.0, write=10.0, pool=15.0)
    async with httpx.AsyncClient(
        headers=DEFAULT_HEADERS,
        http2=False,
        limits=limits,
        timeout=timeout,
    ) as client:
        console.print(
            f"[bold cyan][Fechamento {uf_up}][/] Re-consultando {len(target_sections):,} seções com votos >17h BRT..."
        )
        await process_uf_via_api(
            client=client,
            config=config,
            uf=uf_up,
            sections=target_sections,
            p_tag=p_tag,
            partial_csv=partial_csv,
            concurrency=concurrency,
        )

    if partial_csv.exists():
        merge_partial_csv_into_parquet(partial_csv, final_parquet)
        console.print(
            f"[bold green]✔ Fechamento {uf_up} atualizado:[/] {len(target_sections):,} seções enriquecidas."
        )
    return final_parquet


async def process_uf(
    config: ElectionConfig,
    uf: str,
    concurrency: int = 48,
    cpu_workers: int = 4,
    force_api: bool = False,
    repair_missing: bool = False,
) -> Path:
    """
    Orquestra o processamento completo de uma UF:
    1. Se o Parquet final da UF já existir e `repair_missing=False`, pula imediatamente.
    2. Se `repair_missing=True`, compara o catálogo cs.json atual com o Parquet da UF e baixa apenas o delta.
    3. Caso contrário, processa a UF completa via CDN ou API em memória.
    """
    uf_up = uf.upper()
    final_parquet = get_uf_checkpoint_parquet(config, uf_up)
    if final_parquet.exists() and not repair_missing:
        console.print(f"[dim]✔ UF {uf_up} já processada em {final_parquet.name}. Pulando...[/]")
        return final_parquet

    partial_csv = get_uf_partial_csv(config, uf_up)

    limits = httpx.Limits(
        max_connections=concurrency + 16,
        max_keepalive_connections=concurrency,
        keepalive_expiry=20.0,
    )
    timeout = httpx.Timeout(connect=10.0, read=25.0, write=10.0, pool=15.0)
    async with httpx.AsyncClient(
        headers=DEFAULT_HEADERS,
        http2=False,
        limits=limits,
        timeout=timeout,
    ) as client:
        sections: list[SectionMeta] = []
        mun_map: dict[str, str] = {}
        p_tag = f"p{config.pleito_pad6}"

        try:
            sections, mun_map, p_tag = await fetch_uf_sections_and_municipios(client, config, uf_up)
        except Exception as exc:
            console.print(f"[yellow]Aviso ao buscar catálogo cs.json de {uf_up}: {exc}[/]")

        if final_parquet.exists() and repair_missing:
            existing_keys = load_parquet_section_keys(final_parquet)
            missing_sections = [
                sec for sec in sections
                if (sec.cd_municipio_tse, sec.nr_zona, sec.nr_secao) not in existing_keys
            ]
            if not missing_sections:
                console.print(f"[dim]✔ UF {uf_up}: 0 seções ausentes (100% completo).[/]")
                return final_parquet

            console.print(
                f"[bold yellow][Delta {uf_up}][/] {len(missing_sections):,} seções ausentes/pendentes "
                f"(de {len(sections):,} no catálogo). Buscando complemento..."
            )
            await process_uf_via_api(
                client=client,
                config=config,
                uf=uf_up,
                sections=missing_sections,
                p_tag=p_tag,
                partial_csv=partial_csv,
                concurrency=concurrency,
            )
            if partial_csv.exists():
                before_cnt = len(existing_keys)
                merge_partial_csv_into_parquet(partial_csv, final_parquet)
                after_cnt = len(load_parquet_section_keys(final_parquet))
                console.print(
                    f"[bold green]✔ Delta {uf_up} mesclado:[/] +{after_cnt - before_cnt:,} seções recuperadas "
                    f"(total agora: {after_cnt:,})."
                )
            return final_parquet

        cdn_url = config.cdn_zip_url(uf_up)
        cdn_size = None if force_api else await check_cdn_zip_available(client, cdn_url)

        if cdn_size is not None:
            tmp_zip = TMP_DIR / f"bu_imgbu_logjez_rdv_vscmr_{config.year}_{config.turn}t_{uf_up}.zip"
            try:
                await download_cdn_zip_temporarily(client, cdn_url, tmp_zip, uf_up)
                process_uf_from_cdn_zip(
                    zip_path=tmp_zip,
                    uf=uf_up,
                    mun_map=mun_map,
                    config=config,
                    partial_csv=partial_csv,
                    max_workers=cpu_workers,
                )
            finally:
                # Garante que o arquivo .zip temporário NUNCA seja retido em disco
                if tmp_zip.exists():
                    tmp_zip.unlink()
                    console.print(f"[dim]Arquivo temporário {tmp_zip.name} removido para liberar disco.[/]")
        else:
            if not sections:
                raise RuntimeError(
                    f"Nem o ZIP no CDN nem o catálogo cs.json estão disponíveis para {uf_up}."
                )
            await process_uf_via_api(
                client=client,
                config=config,
                uf=uf_up,
                sections=sections,
                p_tag=p_tag,
                partial_csv=partial_csv,
                concurrency=concurrency,
            )

    if partial_csv.exists():
        finalize_uf_parquet(partial_csv, final_parquet)
        console.print(f"[bold green]✔ UF {uf_up} concluída -> {final_parquet.name}[/]")
    else:
        console.print(f"[yellow]Nenhum dado de seção retornado para a UF {uf_up}.[/]")

    return final_parquet
