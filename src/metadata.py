from __future__ import annotations

from dataclasses import dataclass
import html
import httpx

from src.config import ElectionConfig


@dataclass(frozen=True, slots=True)
class SectionMeta:
    sg_uf: str
    cd_municipio_tse: str
    nm_municipio: str
    nr_zona: str
    nr_secao: str


def _candidate_pleito_tags(pleito_code: str) -> list[str]:
    """
    Gera variações de zero-padding para o código de pleito (ex: p003221, p0003221, p03221)
    para garantir compatibilidade com pleitos de 3 ou 4 dígitos no servidor do TSE.
    """
    candidates = [
        f"p{pleito_code.zfill(6)}",
        f"p000{pleito_code}",
        f"p{pleito_code.zfill(5)}",
    ]
    # Remove duplicatas mantendo a ordem
    return list(dict.fromkeys(candidates))


async def fetch_uf_sections_and_municipios(
    client: httpx.AsyncClient,
    config: ElectionConfig,
    uf: str,
) -> tuple[list[SectionMeta], dict[str, str], str]:
    """
    Baixa o arquivo JSON de configuração de seções (`cs.json`) de uma UF no TSE.

    Retorna:
        - Lista de todas as seções (`SectionMeta`) da UF
        - Dicionário `{cd_municipio_tse: nm_municipio}`
        - O prefixo `p_tag` validado (ex: `'p003221'`)
    """
    uf_low = uf.lower()
    uf_up = uf.upper()
    last_err: Exception | None = None

    for p_tag in _candidate_pleito_tags(config.pleito_code):
        url = (
            f"https://resultados.tse.jus.br/oficial/ele{config.year}/arquivo-urna/{config.pleito_code}"
            f"/config/{uf_low}/{uf_low}-{p_tag}-cs.json"
        )
        try:
            resp = await client.get(url, timeout=30.0)
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            data = resp.json()
            sections: list[SectionMeta] = []
            mun_map: dict[str, str] = {}

            for abr in data.get("abr", []):
                for mu in abr.get("mu", []):
                    cd_mun = str(mu.get("cd", "")).zfill(5)
                    nm_mun = html.unescape(str(mu.get("nm", "")).strip())
                    mun_map[cd_mun] = nm_mun
                    for zon in mu.get("zon", []):
                        cd_zon = str(zon.get("cd", "")).zfill(4)
                        for sec in zon.get("sec", []):
                            # Ignora seções agregadas se houver indicação apenas da principal,
                            # pois na urna os votos das agregadas ficam na seção principal (`ns`).
                            ns = str(sec.get("ns", "")).zfill(4)
                            if ns:
                                sections.append(
                                    SectionMeta(
                                        sg_uf=uf_up,
                                        cd_municipio_tse=cd_mun,
                                        nm_municipio=nm_mun,
                                        nr_zona=cd_zon,
                                        nr_secao=ns,
                                    )
                                )
            return sections, mun_map, p_tag
        except Exception as exc:
            last_err = exc

    raise RuntimeError(
        f"Não foi possível obter o catálogo cs.json para a UF {uf_up} "
        f"(pleito {config.pleito_code}): {last_err}"
    )
