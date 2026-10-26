from __future__ import annotations

import io
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass

import py7zr

from src.config import UF_TO_REGIAO, get_brt_cutoff_time_str, local_time_to_brt_str

# Padrão de nome de arquivo de urna:
# 2026: o03221rr0312300070001-log.jez
# 2022: o00407-7107200010005.logjez
FILENAME_RE = re.compile(
    r"o\d+(?:[a-z]{2}|-)(\d{5})(\d{4})(\d{4})(?:-log)?\.(?:logjez|jez)$",
    re.IGNORECASE,
)

# String exata gravada pelo aplicativo VOTA da urna eletrônica a cada eleitor que conclui o voto
VOTE_COMPUTED_MARKER = b"O voto do eleitor foi computado"

# Marcador principal de fechamento da urna (confirmação pelo presidente da seção) e fallbacks
CLOSING_MARKERS: tuple[bytes, ...] = (
    b"Procedimento de encerramento confirmado",
    b"Inicio do Encerramento",
    b"Gerando relat\xf3rio [BU]",
    b"Gerando arquivo de resultado [bu.dat]",
)

# Verifica se o binário nativo `7z` ou `7zr` está disponível (opcional, para aceleração)
SYSTEM_7Z_BIN = shutil.which("7z") or shutil.which("7za") or shutil.which("7zr")


@dataclass(slots=True)
class SectionVoteResult:
    sg_uf: str
    nm_regiao: str
    cd_municipio_tse: str
    nm_municipio: str
    nr_zona: str
    nr_secao: str
    total_votos: int
    votos_apos_17h_local: int
    votos_apos_17h_brt: int
    hora_fechamento_urna_brt: str | None = None


def parse_ids_from_filename(filename: str) -> tuple[str, str, str] | None:
    """
    Extrai (cd_municipio_tse, nr_zona, nr_secao) do nome do arquivo .logjez / -log.jez.
    Exemplos:
      - 'o03221rr0312300070001-log.jez' -> ('03123', '0007', '0001')
      - 'o00407-7107200010005.logjez'   -> ('71072', '0001', '0005')
    """
    basename = filename.rsplit("/", 1)[-1]
    match = FILENAME_RE.search(basename)
    if not match:
        return None
    return match.group(1), match.group(2), match.group(3)


def extract_logd_bytes_in_memory(logjez_bytes: bytes) -> list[bytes]:
    """
    Descompacta um arquivo .jez / .logjez inteiramente em memória RAM:
    - Suporta formato ZIP ('PK\\x03\\x04', padrão das urnas em 2026) direto via `zipfile.ZipFile`
    - Suporta formato 7-Zip ('7z\\xbc\\xaf\\x27\\x1c', padrão 2022) via `py7zr` em `/dev/shm`
    Retorna os bytes de todos os arquivos `logd*.dat` contidos no pacote.
    """
    if not logjez_bytes:
        return []

    # 1. Caminho rápido 2026: pacote ZIP em memória (PK\x03\x04)
    if logjez_bytes[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(logjez_bytes), mode="r") as zf:
            all_names = zf.namelist()
            target_names = [
                name for name in all_names
                if name.lower().endswith(".dat") and "logd" in name.lower()
            ]
            if not target_names:
                target_names = all_names
            return [zf.read(name) for name in target_names]

    # 2. Caminho 7-Zip (py7zr em /dev/shm)
    shm_dir = "/dev/shm" if os.path.isdir("/dev/shm") and os.access("/dev/shm", os.W_OK) else None

    try:
        with tempfile.TemporaryDirectory(dir=shm_dir, prefix="logjez_") as tmpdir:
            with py7zr.SevenZipFile(io.BytesIO(logjez_bytes), mode="r") as archive:
                all_names = archive.getnames()
                target_names = [
                    name for name in all_names
                    if name.lower().endswith(".dat") and "logd" in name.lower()
                ]
                if not target_names:
                    target_names = all_names
                archive.extract(path=tmpdir, targets=target_names)

            blobs: list[bytes] = []
            for p in sorted(Path(tmpdir).rglob("*")):
                if p.is_file():
                    blobs.append(p.read_bytes())
            return blobs
    except Exception:
        if SYSTEM_7Z_BIN:
            proc = subprocess.run(
                [SYSTEM_7Z_BIN, "e", "-si", "-so", "*.dat"],
                input=logjez_bytes,
                capture_output=True,
                check=False,
            )
            if proc.stdout:
                return [proc.stdout]
        raise


def count_votes_in_logd(
    logd_blobs: list[bytes],
    election_date: str,
    next_day_date: str,
    brt_cutoff_str: str,
) -> tuple[int, int, int]:
    """
    Conta de forma otimizada em bytes todas as ocorrências de 'O voto do eleitor foi computado'
    no dia do 2º turno (e eventual virada de meia-noite até 05:59:59 do dia seguinte).

    Retorna:
        (total_votos, votos_apos_17h_local, votos_apos_17h_brt)
    """
    date_prefix = election_date.encode("ascii") + b" "
    next_date_prefix = next_day_date.encode("ascii") + b" "
    local_cutoff = b"17:00:00"
    brt_cutoff = brt_cutoff_str.encode("ascii")

    total_votos = 0
    votos_apos_17h_local = 0
    votos_apos_17h_brt = 0

    # Caso haja mais de um arquivo logd*.dat (ex: substituição de urna na seção),
    # deduplicamos as linhas de voto para evitar contagem dupla de histórico copiado.
    dedup_lines: set[bytes] | None = set() if len(logd_blobs) > 1 else None

    for blob in logd_blobs:
        # Busca direta pela substring em bytes (evita decodificar dezenas de milhares de linhas irrelevantes)
        search_pos = 0
        while True:
            idx = blob.find(VOTE_COMPUTED_MARKER, search_pos)
            if idx == -1:
                break

            # Encontra o início e o fim da linha onde o marcador apareceu
            line_start = blob.rfind(b"\n", 0, idx)
            line_start = 0 if line_start == -1 else line_start + 1
            line_end = blob.find(b"\n", idx)
            if line_end == -1:
                line_end = len(blob)

            line = blob[line_start:line_end].rstrip(b"\r")
            search_pos = line_end + 1

            if dedup_lines is not None:
                if line in dedup_lines:
                    continue
                dedup_lines.add(line)

            # Formato da linha: "DD/MM/YYYY HH:MM:SS\tINFO\t..."
            if line.startswith(date_prefix) and len(line) >= 19:
                hh_mm_ss = line[11:19]
                total_votos += 1
                if hh_mm_ss >= local_cutoff:
                    votos_apos_17h_local += 1
                if hh_mm_ss >= brt_cutoff:
                    votos_apos_17h_brt += 1
            elif line.startswith(next_date_prefix) and len(line) >= 19:
                hh_mm_ss = line[11:19]
                # Votos de eleitores da fila que concluíram logo após a meia-noite
                if hh_mm_ss < b"06:00:00":
                    total_votos += 1
                    votos_apos_17h_local += 1
                    votos_apos_17h_brt += 1

    return total_votos, votos_apos_17h_local, votos_apos_17h_brt


def extract_closing_time_in_logd(
    logd_blobs: list[bytes],
    election_date: str,
    next_day_date: str,
    sg_uf: str,
    cd_municipio_tse: str,
) -> str | None:
    """
    Extrai o horário de fechamento da urna ('Procedimento de encerramento confirmado',
    com fallback para 'Inicio do Encerramento') no dia do pleito e converte para o
    Horário de Brasília (BRT) no formato 'HH:MM:SS'.
    """
    date_prefix = election_date.encode("ascii") + b" "
    next_date_prefix = next_day_date.encode("ascii") + b" "

    for marker in CLOSING_MARKERS:
        found_local_time: str | None = None
        for blob in logd_blobs:
            search_pos = 0
            while True:
                idx = blob.find(marker, search_pos)
                if idx == -1:
                    break
                line_start = blob.rfind(b"\n", 0, idx)
                line_start = 0 if line_start == -1 else line_start + 1
                line_end = blob.find(b"\n", idx)
                if line_end == -1:
                    line_end = len(blob)

                line = blob[line_start:line_end].rstrip(b"\r")
                search_pos = line_end + 1

                if line.startswith(date_prefix) and len(line) >= 19:
                    hh_mm_ss = line[11:19]
                    if hh_mm_ss >= b"12:00:00":
                        found_local_time = hh_mm_ss.decode("ascii", errors="ignore")
                elif line.startswith(next_date_prefix) and len(line) >= 19:
                    hh_mm_ss = line[11:19]
                    if hh_mm_ss < b"06:00:00":
                        found_local_time = hh_mm_ss.decode("ascii", errors="ignore")

        if found_local_time:
            return local_time_to_brt_str(found_local_time, sg_uf, cd_municipio_tse)

    return None


def process_multiple_logjez_bytes(
    logjez_bytes_list: list[bytes],
    sg_uf: str,
    cd_municipio_tse: str,
    nm_municipio: str,
    nr_zona: str,
    nr_secao: str,
    election_date: str,
    next_day_date: str,
) -> SectionVoteResult:
    """
    Processa os bytes de um ou mais arquivos .logjez (caso a seção tenha múltiplos hashes
    no aux.json por substituição de urna) em memória e retorna a contagem deduplicada da seção.
    """
    uf_up = sg_uf.upper()
    mun_pad = cd_municipio_tse.zfill(5)
    zona_pad = nr_zona.zfill(4)
    secao_pad = nr_secao.zfill(4)

    brt_cutoff_str = get_brt_cutoff_time_str(uf_up, mun_pad)
    all_blobs: list[bytes] = []
    for raw_b in logjez_bytes_list:
        all_blobs.extend(extract_logd_bytes_in_memory(raw_b))

    total, after_local, after_brt = count_votes_in_logd(
        logd_blobs=all_blobs,
        election_date=election_date,
        next_day_date=next_day_date,
        brt_cutoff_str=brt_cutoff_str,
    )
    closing_brt = (
        extract_closing_time_in_logd(
            logd_blobs=all_blobs,
            election_date=election_date,
            next_day_date=next_day_date,
            sg_uf=uf_up,
            cd_municipio_tse=mun_pad,
        )
        if after_brt > 0
        else None
    )

    return SectionVoteResult(
        sg_uf=uf_up,
        nm_regiao=UF_TO_REGIAO.get(uf_up, "Desconhecida"),
        cd_municipio_tse=mun_pad,
        nm_municipio=nm_municipio or f"MUNICIPIO_{mun_pad}",
        nr_zona=zona_pad,
        nr_secao=secao_pad,
        total_votos=total,
        votos_apos_17h_local=after_local,
        votos_apos_17h_brt=after_brt,
        hora_fechamento_urna_brt=closing_brt,
    )


def process_logjez_bytes(
    logjez_bytes: bytes,
    sg_uf: str,
    cd_municipio_tse: str,
    nm_municipio: str,
    nr_zona: str,
    nr_secao: str,
    election_date: str,
    next_day_date: str,
) -> SectionVoteResult:
    """
    Processa os bytes de um único arquivo .logjez em memória e retorna a contagem da seção.
    """
    return process_multiple_logjez_bytes(
        logjez_bytes_list=[logjez_bytes],
        sg_uf=sg_uf,
        cd_municipio_tse=cd_municipio_tse,
        nm_municipio=nm_municipio,
        nr_zona=nr_zona,
        nr_secao=nr_secao,
        election_date=election_date,
        next_day_date=next_day_date,
    )
