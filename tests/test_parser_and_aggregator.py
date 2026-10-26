from __future__ import annotations

import io
from pathlib import Path
import tempfile
import unittest

import duckdb
import py7zr

from src.aggregator import run_aggregations
import src.config as cfg_mod
from src.config import PRESET_ELECTIONS, get_brt_cutoff_time_str
from src.parser import parse_ids_from_filename, process_logjez_bytes


def make_synthetic_logjez(lines: list[str]) -> bytes:
    """Cria um arquivo .logjez (7-Zip contendo logd.dat em ISO-8859-1) em memória."""
    raw_log = ("\r\n".join(lines) + "\r\n").encode("iso-8859-1")
    buf = io.BytesIO()
    with py7zr.SevenZipFile(buf, mode="w") as archive:
        archive.writestr(raw_log, "logd.dat")
    return buf.getvalue()


class TestParserAndAggregator(unittest.TestCase):
    def test_parse_ids_from_filename(self) -> None:
        ids = parse_ids_from_filename("o03221-7107200010005.logjez")
        self.assertEqual(ids, ("71072", "0001", "0005"))

    def test_brt_cutoff_offsets(self) -> None:
        # SP (UTC-3 = BRT) -> 17:00:00
        self.assertEqual(get_brt_cutoff_time_str("SP", "71072"), "17:00:00")
        # AC (UTC-5 = BRT-2) -> 15:00:00
        self.assertEqual(get_brt_cutoff_time_str("AC", "01392"), "15:00:00")
        # AM capital Manaus (UTC-4 = BRT-1) -> 16:00:00
        self.assertEqual(get_brt_cutoff_time_str("AM", "02550"), "16:00:00")
        # AM Tabatinga (UTC-5 = BRT-2) -> 15:00:00
        self.assertEqual(get_brt_cutoff_time_str("AM", "98477"), "15:00:00")
        # PE Fernando de Noronha (UTC-2 = BRT+1) -> 18:00:00
        self.assertEqual(get_brt_cutoff_time_str("PE", "30015"), "18:00:00")

    def test_process_logjez_bytes_in_memory(self) -> None:
        # Simula uma seção no Acre (UTC-5: encerramento oficial às 15h locais = 17h BRT)
        sample_lines = [
            "25/10/2026 06:05:00\tINFO\t67305985\tVOTA\tUrna pronta para receber votos\tAAAA",
            "25/10/2026 10:15:22\tINFO\t67305985\tVOTA\tO voto do eleitor foi computado\tBBBB",
            "25/10/2026 14:59:59\tINFO\t67305985\tVOTA\tO voto do eleitor foi computado\tCCCC",
            "25/10/2026 15:10:00\tINFO\t67305985\tVOTA\tO voto do eleitor foi computado\tDDDD",
            "25/10/2026 17:05:12\tINFO\t67305985\tVOTA\tO voto do eleitor foi computado\tEEEE",
            "25/10/2026 17:08:45\tINFO\t67305985\tVOTA\tProcedimento de encerramento confirmado\tEEEE",
            # Voto do 1º turno no mesmo log (deve ser ignorado)
            "04/10/2026 17:30:00\tINFO\t67305985\tVOTA\tO voto do eleitor foi computado\tFFFF",
        ]
        logjez_bytes = make_synthetic_logjez(sample_lines)
        res = process_logjez_bytes(
            logjez_bytes=logjez_bytes,
            sg_uf="AC",
            cd_municipio_tse="01392",
            nm_municipio="RIO BRANCO",
            nr_zona="0001",
            nr_secao="0010",
            election_date="25/10/2026",
            next_day_date="26/10/2026",
        )
        self.assertEqual(res.total_votos, 4)
        # Apenas 1 voto tem horário >= 17:00:00 no relógio da urna (17:05:12)
        self.assertEqual(res.votos_apos_17h_local, 1)
        # 2 votos têm horário >= 15:00:00 no relógio da urna (15:10:00 e 17:05:12 = após 17h BRT)
        self.assertEqual(res.votos_apos_17h_brt, 2)
        # Horário de fechamento 17:08:45 local no Acre (UTC-5, offset -2) -> 19:08:45 BRT
        self.assertEqual(res.hora_fechamento_urna_brt, "19:08:45")

    def test_duckdb_aggregations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            orig_ckpt = cfg_mod.CHECKPOINT_DIR
            orig_out = cfg_mod.OUTPUT_DIR
            try:
                cfg_mod.CHECKPOINT_DIR = tmp_path / "checkpoints"
                cfg_mod.OUTPUT_DIR = tmp_path / "output"
                cfg_mod.CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

                # Insere também nos atributos importados pelo módulo aggregator
                import src.aggregator as agg_mod
                agg_mod.CHECKPOINT_DIR = cfg_mod.CHECKPOINT_DIR
                agg_mod.OUTPUT_DIR = cfg_mod.OUTPUT_DIR

                pq_file = cfg_mod.CHECKPOINT_DIR / "secoes_2026_2t_SP.parquet"
                con = duckdb.connect(":memory:")
                con.execute(
                    f"""
                    COPY (
                        SELECT
                            'SP' AS sg_uf,
                            'Sudeste' AS nm_regiao,
                            '71072' AS cd_municipio_tse,
                            'SÃO PAULO' AS nm_municipio,
                            '0001' AS nr_zona,
                            '0001' AS nr_secao,
                            320 AS total_votos,
                            12 AS votos_apos_17h_local,
                            12 AS votos_apos_17h_brt
                        UNION ALL
                        SELECT
                            'SP', 'Sudeste', '71072', 'SÃO PAULO', '0001', '0002', 280, 0, 0
                    ) TO '{pq_file.as_posix()}' (FORMAT PARQUET);
                    """
                )
                con.close()

                outputs = run_aggregations(PRESET_ELECTIONS[2026])
                self.assertTrue(outputs["secao_csv"].exists())
                self.assertTrue(outputs["municipio_csv"].exists())
                self.assertTrue(outputs["uf_csv"].exists())
                self.assertTrue(outputs["regiao_csv"].exists())
                self.assertTrue(outputs["brasil_csv"].exists())
            finally:
                cfg_mod.CHECKPOINT_DIR = orig_ckpt
                cfg_mod.OUTPUT_DIR = orig_out


if __name__ == "__main__":
    unittest.main()
