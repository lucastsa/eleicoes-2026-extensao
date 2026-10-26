# Guia de Execução — Contagem de Votos Após as 17h

Instruções detalhadas para execução do pipeline em Python que baixa e processa em memória os arquivos de log de urna (`.logjez` -> `logd.dat`) das seções eleitorais do 2º turno das Eleições Gerais de 2026 (pleito `3221`).

---

## Pré-requisitos e Ambiente

Certifique-se de que o ambiente virtual está configurado e com as dependências instaladas:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

---

## Como Executar

### 1. Executar para todas as UFs (Brasil inteiro + Exterior)
```bash
.venv/bin/python main.py
```

### 2. Executar para uma ou mais UFs específicas
```bash
.venv/bin/python main.py --uf AC RR AP
```

### 3. Ajustar concorrência de rede e núcleos de CPU
```bash
.venv/bin/python main.py --concurrency 24 --workers 4
```

### 4. Apenas regerar agregações a partir dos checkpoints já processados
```bash
.venv/bin/python main.py --aggregate-only
```

---

## Arquivos de Saída (`data/output/`)

Ao final do processamento, são gerados arquivos `.csv` e `.parquet` em 5 níveis de granularidade:

- `data/output/votos_apos_17h_secao.{csv,parquet}`
- `data/output/votos_apos_17h_municipio.{csv,parquet}`
- `data/output/votos_apos_17h_uf.{csv,parquet}`
- `data/output/votos_apos_17h_regiao.{csv,parquet}`
- `data/output/votos_apos_17h_brasil.{csv,parquet}`
