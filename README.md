# Análise do Impacto da Extensão da Votação após as 17h — 2º Turno (Eleições 2026)

Este repositório contém uma ferramenta de extração e análise de dados eleitorais em nível de seção eleitoral, projetada para auditar e mensurar o impacto da extensão excepcional do horário de votação ocorrida no segundo turno das Eleições Gerais brasileiras em **25 de outubro de 2026**.

---

## 1. Contexto e Motivação

No domingo de 25 de outubro de 2026, durante o 2º turno do pleito eleitoral, foram registradas graves denúncias e ocorrências de **insuficiência, paralisação e redução injustificada da frota de transporte público coletivo gratuito** em diversas capitais e regiões metropolitanas (com destaque inicial para municípios baianos como Salvador, Feira de Santana e Lauro de Freitas, estendendo-se a outras localidades), em afronta ao dever de garantia de gratuidade fixado pelo Supremo Tribunal Federal na **ADPF 1013**.

Diante do risco direto de cerceamento ao exercício do sufrágio por parte dos eleitores afetados pela carência de transporte, a *Coligação Brasil Pronto Pra Mais* ajuizou no STF a **Reclamação (RCL) 101673**. Por volta das 16h30, o relator, ministro **Cristiano Zanin**, deferiu medida liminar determinando a prorrogação do horário de votação até as 19h (horário de Brasília) em todos os municípios brasileiros, naqueles locais onde as urnas ainda não haviam sido encerradas às 17h.

### Documentos e Fontes Oficiais do STF:
- 🏛️ **Notícia Oficial do STF:** [STF prorroga votação até as 19h em locais onde urnas permaneceram abertas após as 17h](https://noticias.stf.jus.br/postsnoticias/stf-prorroga-votacao-ate-as-19h-em-locais-onde-urnas-permaneceram-abertas-apos-as-17h/)
- 📄 **Decisão Liminar (PDF):** [Íntegra da Decisão Liminar na RCL 101673 (Rel. Min. Cristiano Zanin)](https://noticias-stf-wp-prd.s3.sa-east-1.amazonaws.com/wp-content/uploads/wpallimport/uploads/2026/10/25183103/liminar-urgente.pdf)
- 📄 **Esclarecimento da Liminar (PDF):** [Despacho de Esclarecimento sobre o Alcance e a Impossibilidade de Reabertura de Urnas](https://noticias-stf-wp-prd.s3.sa-east-1.amazonaws.com/wp-content/uploads/wpallimport/uploads/2026/10/25183217/esclarecimento.pdf)

---

## 2. A Impossibilidade Técnica de Reabertura das Urnas Eletrônicas e o Fechamento às 17h

Apesar da abrangência nacional pretendida pela medida judicial, a realidade operacional do encerramento das seções esbarrou em uma premissa técnica e estrutural do sistema eletrônico de votação brasileiro: **as urnas eletrônicas não podem ser reabertas após o seu encerramento**.

1. **Comando Irreversível e Boletim de Urna (BU):** Conforme os procedimentos da Justiça Eleitoral e as resoluções de atos gerais do processo eleitoral, ao término dos trabalhos a mesa receptora executa o comando de encerramento da votação. Imediatamente, o sistema criptografa as mídias de resultado, gera as assinaturas digitais e emite as vias físicas do Boletim de Urna. A partir desse instante, a urna entra em travamento lógico definitivo, não existindo qualquer recurso ou chave no software que permita desfazer o fechamento para receber novos votos.
2. **Seções Encerradas às 17h apesar da Ordem Judicial:** Como a liminar foi concedida por volta das 16h30 — a poucos minutos do término ordinário da votação —, milhares de mesários e chefes de cartório não tiveram tempo hábil para receber a notificação judicial e procederam ao fechamento regular das seções pontualmente às 17h.
3. **Reconhecimento Judicial Expresso:** Diante das consultas imediatas dos Tribunais Regionais Eleitorais (TREs), o próprio ministro relator expediu despacho de esclarecimento confirmando que a prorrogação até as 19h se aplicava estritamente às seções onde a votação ainda não havia sido encerrada, sendo inviável exigir ou proceder à reabertura daquelas que já haviam emitido o Boletim de Urna às 17h.

### Fontes Normativas e Oficiais:
- 📄 **Despacho de Esclarecimento do STF:** [Esclarecimento da Liminar — Confirmação de que urnas encerradas não são reabertas](https://noticias-stf-wp-prd.s3.sa-east-1.amazonaws.com/wp-content/uploads/wpallimport/uploads/2026/10/25183217/esclarecimento.pdf)
- 🏛️ **Portal do STF:** [Comunicação oficial do Tribunal confirmando o limite de alcance da decisão às urnas abertas](https://noticias.stf.jus.br/postsnoticias/stf-prorroga-votacao-ate-as-19h-em-locais-onde-urnas-permaneceram-abertas-apos-as-17h/)

---

## 3. Limitação Metodológica Crucial: Votos da Fila das 17h vs. Votos da Prorrogação

> [!IMPORTANT]
> **Ressalva Metodológica sobre a Imprecisão na Atribuição Causal dos Votos:**
> 
> O algoritmo deste projeto contabiliza e agrega de forma bruta **todos os votos com registro de horário posterior às 17:00:00**, rotulando-os como votos decorrentes do período estendido. **No entanto, essa premissa é metodologicamente imprecisa.**
> 
> * **O Direito Adquirido da Fila com Senha:** De acordo com o Código Eleitoral brasileiro (Lei nº 4.737/1965, art. 153) e as normas de processo eleitoral do TSE, os eleitores que já se encontravam na fila da seção às 17h recebem senhas da mesa receptora e mantêm o direito assegurado de votar, independentemente do horário em que forem admitidos à cabine.
> * **Presença Natural de Votos Pós-17h em Eleições Ordinárias:** Em qualquer eleição regular — mesmo sem qualquer prorrogação judicial extraordinária —, dezenas de milhares de votos são rotineiramente computados entre 17h00 e 18h00+ em virtude de filas, lentidão biométrica ou alta densidade de votantes.
> * **Interpretação como Limite Superior (*Upper Bound*):** Como os logs oficiais da urna eletrônica (`logd.dat`) registram apenas o timestamp exato em que o voto foi digitado e confirmado na urna (sem registrar se o eleitor estava na fila antes das 17h ou se ingressou na seção graças à extensão excepcional até as 19h), os números gerados por este projeto englobam indistintamente:
>   1. O fluxo residual regular de eleitores que já estavam na fila às 17h (votos que ocorreriam de qualquer forma);
>   2. Os eleitores que chegaram aos locais após as 17h beneficiados pelas duas horas adicionais autorizadas pela Justiça.
> 
> Portanto, o resultado do pipeline deve ser interpretado estritamente como um **teto (*upper bound*)** dos votos computados após o horário regular, e não como o efeito causal líquido atribuível unicamente à decisão judicial.

---

## 4. Objetivo do Projeto

Compreendendo essa assimetria territorial e suas limitações analíticas, o objetivo deste repositório é:

1. **Baixar e inspecionar em memória** os arquivos oficiais de log de cada urna eletrônica (`.logjez` contendo o `logd.dat`) disponibilizados publicamente pelo TSE no portal de dados abertos para o 2º turno de 2026 (pleito `3221`).
2. **Contabilizar com precisão de timestamp** os votos digitados e confirmados após as 17h00 (horário de Brasília — BRT).
3. **Agregar os resultados** nas seguintes granularidades geográficas:
   - Seção Eleitoral
   - Município
   - Unidade Federativa (UF)
   - Macrorregião (Norte, Nordeste, Centro-Oeste, Sudeste e Sul)
   - Total Brasil
4. **Quantificar a magnitude** desse contingente de votos e sua correlação com os resultados apurados em cada localidade.

---

## 5. Como Executar e Replicar a Coleta

Para obter instruções completas de instalação, dependências, execução paralela e geração dos arquivos `.csv` e `.parquet`, consulte o arquivo:

👉 **[Guia de Execução (USAGE.md)](USAGE.md)**

---

## 6. Aviso de Transparência e Validação Independente

> [!WARNING]
> **Aviso sobre Validação e Auditoria Externa:**
> Este código e os métodos de contagem implementados **não foram extensamente validados** por auditorias acadêmicas ou periciais formais.
> 
> Todo o desenvolvimento deste projeto foi realizado com a assistência da Inteligência Artificial do **Gemini 4 Argon**.
> 
> Em respeito aos princípios de transparência pública e integridade de dados abertos, **o código-fonte é 100% aberto e público sob a licença MIT**, permitindo e incentivando a reprodução, revisão por pares, correção e validação independente por qualquer pessoa, estatístico, pesquisador ou órgão de imprensa.

---

## 7. Conclusão e Resultados Finais

A coleta e o processamento integral dos logs de urna das **27 Unidades Federativas do Brasil** (**497.895 urnas/seções** distribuídas em **5.571 municípios**) revelaram os seguintes resultados consolidados para os votos computados após o horário oficial de encerramento (**17h00 BRT**):

- **Total de votos computados após as 17h BRT no Brasil:** **45.496 votos** (de um total de **127.697.270** votos computados nos logs em território nacional).
- **Proporção em relação ao total de votantes:** **0,0356%** do eleitorado votante.
- **Número de urnas/seções com votos após as 17h BRT:** **30.730 urnas/seções** (**6,1720%** do total de 497.895 seções; **467.165 seções [93,8280%]** não registraram nenhum voto após as 17h BRT).

### Síntese por Macrorregião (>17h BRT)

| Região | UFs | Municípios | Total de Urnas/Seções | Urnas >17h BRT | % Urnas >17h BRT | Total de Votos | Votos >17h BRT | % Votos >17h BRT |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **Sudeste** | 4 | 1.668 | 203.235 | 13.358 | 6,5727% | 52.838.216 | 15.557 | 0,0294% |
| **Nordeste** | 9 | 1.794 | 140.828 | 8.563 | 6,0805% | 36.280.754 | 10.046 | 0,0277% |
| **Sul** | 3 | 1.191 | 72.015 | 2.058 | 2,8577% | 18.683.954 | 2.218 | 0,0119% |
| **Norte** | 7 | 450 | 43.769 | 4.047 | 9,2463% | 10.307.275 | 14.630 | 0,1419% |
| **Centro-Oeste** | 4 | 468 | 38.048 | 2.704 | 7,1068% | 9.587.071 | 3.045 | 0,0318% |
| **TOTAL BRASIL** | **27** | **5.571** | **497.895** | **30.730** | **6,1720%** | **127.697.270** | **45.496** | **0,0356%** |

> **Nota sobre o Exterior (`ZZ`) e Conciliação com o Total Geral do TSE:** As seções instaladas no Exterior (`ZZ`) seguem o fuso horário local de cada país (08h às 17h locais), não se aplicando a unificação pelo horário de Brasília nem a extensão decorrente da liminar. No escopo `ZZ` foram apuradas **1.310 urnas/seções** em **146 localidades** (**380.229 votos totais**), com **417 votos** (`0,1097%`) registrados após as 17h locais em **252 urnas** (`19,2366%`). Somando o Brasil (`127.697.270`) e o Exterior (`380.229`), os logs processados abrangem **128.077.499 votos** em **499.205 seções** (**99,88%** dos **128.236.074** votos totais divulgados pelo TSE; a diferença residual de 0,12% decorre de seções com substituição de urna sem cópia do log da primeira mídia ou votação em cédula/Sistema de Apuração).

### Conclusão: Os votos após as 17h BRT poderiam alterar o resultado da eleição?

**Não.** Mesmo sob a premissa hipotética mais extrema — assumindo que **100% dos 45.496 votos computados após as 17h BRT tivessem sido dados ao 1º colocado e migrassem integralmente para o 2º colocado** — o resultado final do pleito não seria alterado:
1. **Fluxo residual por seção (`~1,48` voto por urna):** Nas 30.730 urnas que registraram algum voto após as 17h BRT, a média foi de apenas **1,48 voto por urna**, refletindo essencialmente o último eleitor já habilitado na cabina às 16h59 BRT ou pequenas filas residuais com senha.
2. **Impacto matemático diante da margem (~2,5 milhões de votos):** Como cada voto transferido do 1º para o 2º colocado reduz a vantagem em 2 votos, uma migração de 100% desses votos alteraria a diferença entre os candidatos em no máximo **90.992 votos** ($2 \times 45.496$), o que equivale a apenas **3,64%** de uma diferença de ~2,5 milhões de votos (ou **1,82%** caso fossem anulados).

📊 **Para consultar a tabela detalhada por Unidade Federativa (UF) e a análise completa, acesse:**
👉 **[Relatório Completo de Votos e Urnas Após as 17h BRT (RELATORIO_VOTOS_APOS_17H.md)](RELATORIO_VOTOS_APOS_17H.md)**
