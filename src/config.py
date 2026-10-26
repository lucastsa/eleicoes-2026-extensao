from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
TMP_DIR = DATA_DIR / "tmp"
CHECKPOINT_DIR = DATA_DIR / "checkpoints"
OUTPUT_DIR = DATA_DIR / "output"

# Lista oficial de UFs do TSE ordenada dos menores estados (menos seções) para os maiores
ALL_UFS: tuple[str, ...] = (
    "RR", "ZZ", "AP", "AC", "TO", "RO", "SE", "DF", "AL",
    "MS", "RN", "AM", "PI", "MT", "ES", "PB", "PA", "GO",
    "SC", "MA", "PE", "CE", "RS", "PR", "BA", "RJ", "MG",
    "SP",
)

# Mapeamento de UF para Macrorregião (IBGE + Exterior)
UF_TO_REGIAO: dict[str, str] = {
    # Norte
    "AC": "Norte",
    "AM": "Norte",
    "AP": "Norte",
    "PA": "Norte",
    "RO": "Norte",
    "RR": "Norte",
    "TO": "Norte",
    # Nordeste
    "AL": "Nordeste",
    "BA": "Nordeste",
    "CE": "Nordeste",
    "MA": "Nordeste",
    "PB": "Nordeste",
    "PE": "Nordeste",
    "PI": "Nordeste",
    "RN": "Nordeste",
    "SE": "Nordeste",
    # Centro-Oeste
    "DF": "Centro-Oeste",
    "GO": "Centro-Oeste",
    "MS": "Centro-Oeste",
    "MT": "Centro-Oeste",
    # Sudeste
    "ES": "Sudeste",
    "MG": "Sudeste",
    "RJ": "Sudeste",
    "SP": "Sudeste",
    # Sul
    "PR": "Sul",
    "RS": "Sul",
    "SC": "Sul",
    # Exterior
    "ZZ": "Exterior",
}

# Offset padrão em horas do relógio local da UF em relação ao Horário de Brasília (BRT = UTC-3)
# Ex.: -1 significa UTC-4 (quando são 17:00 em Brasília, são 16:00 no relógio local).
UF_DEFAULT_BRT_OFFSET: dict[str, int] = {
    "AC": -2,  # UTC-5 (17h BRT = 15h local)
    "AM": -1,  # UTC-4 na maior parte (exceto 13 municípios no sudoeste do AM que são UTC-5)
    "RO": -1,  # UTC-4
    "RR": -1,  # UTC-4
    "MT": -1,  # UTC-4
    "MS": -1,  # UTC-4
}

# Municípios com fuso horário diferente do padrão da sua UF (código TSE de 5 dígitos):
# - Fernando de Noronha (PE): UTC-2 (+1h em relação a Brasília -> 17h BRT = 18h local)
# - Municípios do oeste do Amazonas (America/Eirunepe): UTC-5 (-2h em relação a Brasília -> 17h BRT = 15h local)
MUNICIPIO_BRT_OFFSET_OVERRIDE: dict[str, int] = {
    "30015": +1,  # Fernando de Noronha (PE)
    "02917": -2,  # Amaturá (AM)
    "02054": -2,  # Atalaia do Norte (AM)
    "02135": -2,  # Benjamin Constant (AM)
    "02291": -2,  # Eirunepé (AM)
    "02313": -2,  # Envira (AM)
    "02020": -2,  # Guajará (AM)
    "02399": -2,  # Ipixuna (AM)
    "98370": -2,  # Itamarati (AM)
    "02496": -2,  # Jutaí (AM)
    "02755": -2,  # São Paulo de Olivença (AM)
    "98477": -2,  # Tabatinga (AM)
    "98515": -2,  # Tonantins (AM)
}


def get_brt_cutoff_time_str(sg_uf: str, cd_municipio_tse: str) -> str:
    """
    Retorna a string de horário 'HH:MM:SS' equivalente às 17:00:00 (Horário de Brasília)
    no relógio local do município/UF.
    No Exterior (ZZ), o encerramento ocorre às 17:00:00 do horário local de cada seção.
    """
    uf = sg_uf.upper()
    if uf == "ZZ":
        return "17:00:00"
    mun_pad = cd_municipio_tse.zfill(5)
    offset = MUNICIPIO_BRT_OFFSET_OVERRIDE.get(mun_pad, UF_DEFAULT_BRT_OFFSET.get(uf, 0))
    cutoff_hour = 17 + offset
    return f"{cutoff_hour:02d}:00:00"


@dataclass(frozen=True)
class ElectionConfig:
    year: int
    turn: int
    pleito_code: str
    election_date: str  # DD/MM/YYYY
    next_day_date: str  # DD/MM/YYYY (para capturar votos que cruzaram a meia-noite)

    @property
    def pleito_pad6(self) -> str:
        """Código do pleito com 6 dígitos usado nos arquivos de configuração (ex: '003221')."""
        return self.pleito_code.zfill(6)

    @property
    def pleito_pad5(self) -> str:
        """Código do pleito com 5 dígitos usado no prefixo 'o' dos arquivos de urna (ex: '03221')."""
        return self.pleito_code.zfill(5)

    def cdn_zip_url(self, uf: str) -> str:
        """URL do pacote consolidado de arquivos de urna por UF no CDN do TSE."""
        uf_up = uf.upper()
        return (
            f"https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes{self.year}"
            f"/arqurnatot/bu_imgbu_logjez_rdv_vscmr_{self.year}_{self.turn}t_{uf_up}.zip"
        )

    def cs_json_url(self, uf: str) -> str:
        """URL do arquivo JSON de configuração de municípios, zonas e seções por UF."""
        uf_low = uf.lower()
        return (
            f"https://resultados.tse.jus.br/oficial/ele{self.year}/arquivo-urna/{self.pleito_code}"
            f"/config/{uf_low}/{uf_low}-p{self.pleito_pad6}-cs.json"
        )

    def section_aux_url(self, uf: str, cd_municipio: str, nr_zona: str, nr_secao: str) -> str:
        """URL do arquivo aux.json da seção eleitoral contendo o hash e lista de arquivos."""
        uf_low = uf.lower()
        m = cd_municipio.zfill(5)
        z = nr_zona.zfill(4)
        s = nr_secao.zfill(4)
        return (
            f"https://resultados.tse.jus.br/oficial/ele{self.year}/arquivo-urna/{self.pleito_code}"
            f"/dados/{uf_low}/{m}/{z}/{s}/p{self.pleito_pad6}-{uf_low}-m{m}-z{z}-s{s}-aux.json"
        )

    def section_logjez_url(
        self,
        uf: str,
        cd_municipio: str,
        nr_zona: str,
        nr_secao: str,
        sec_hash: str,
        filename: str | None = None,
    ) -> str:
        """URL direta do arquivo .logjez de uma seção eleitoral."""
        uf_low = uf.lower()
        m = cd_municipio.zfill(5)
        z = nr_zona.zfill(4)
        s = nr_secao.zfill(4)
        fname = filename or f"o{self.pleito_pad5}-{m}{z}{s}.logjez"
        return (
            f"https://resultados.tse.jus.br/oficial/ele{self.year}/arquivo-urna/{self.pleito_code}"
            f"/dados/{uf_low}/{m}/{z}/{s}/{sec_hash}/{fname}"
        )


PRESET_ELECTIONS: dict[int, ElectionConfig] = {
    2026: ElectionConfig(
        year=2026,
        turn=2,
        pleito_code="3221",
        election_date="25/10/2026",
        next_day_date="26/10/2026",
    ),
    2022: ElectionConfig(
        year=2022,
        turn=2,
        pleito_code="407",
        election_date="30/10/2022",
        next_day_date="31/10/2022",
    ),
}
