# Backtesting e validação histórica

O motor da Fase 5 é um event study determinístico da estratégia existente `BREAKOUT_20D_VOLUME`. Não executa ordens, não constrói carteiras e não altera os critérios do scanner.

## Causalidade e datas

Para uma sessão de sinal `T`, as features e a decisão usam apenas barras com timestamp menor ou igual a `T`. `PREVIOUS_HIGH_20D`, média de volume e liquidez aplicam `shift(1)`, pelo que a barra corrente não entra no respetivo limiar. Só depois de a decisão estar concluída o motor lê barras futuras para calcular outcomes.

Os horizontes 1, 5, 10, 20 e 60 são deslocamentos exatos de sessões XNYS. Uma janela com qualquer sessão ausente é marcada `forward_data_complete=false`; não é encurtada nem preenchida.

Modelos de entrada:

- `SIGNAL_CLOSE`: entrada ao fecho de `T`.
- `NEXT_OPEN`: entrada na abertura de `T+1`; é o modelo recomendado para reduzir viés de execução.

Para cada horizonte são guardados retorno da ação, retorno do SPY e excesso. Para 5, 10, 20 e 60 sessões são também guardados MFE e MAE relativamente ao preço de entrada.

## Universos

- `POINT_IN_TIME` consulta exclusivamente intervalos históricos em `universe_memberships`. Se não existirem, devolve `DATA_UNAVAILABLE`; nunca substitui pela composição atual.
- `FIXED_UNIVERSE_RESEARCH` usa a composição do snapshot atual e inclui obrigatoriamente: "Fixed-universe research. Results may contain survivorship bias and must not be interpreted as a point-in-time S&P 500 backtest."

## Preparar dados sem iniciar chamadas

O dry-run da ingestão não requer API key e não chama a Massive:

```bash
python -m app.cli.ingest_market_data \
  --lookback-years 5 --dry-run --requests-per-minute 5 \
  --output reports/ingestion-5y-estimate.json
```

O relatório contém período, sessões em falta, intervalos mínimos, pedidos estimados e duração mínima à cadência indicada. Para executar realmente, retire `--dry-run`. Também pode usar `--start-date`/`--end-date` ou `--lookback-sessions`.

## Executar

Pré-visualizar cobertura:

```bash
python -m app.cli.run_backtest \
  --universe-mode FIXED_UNIVERSE_RESEARCH \
  --tickers AAPL,MSFT,NVDA \
  --start-date 2025-01-01 --end-date 2025-12-31 \
  --entry-model NEXT_OPEN --dry-run
```

Executar e persistir:

```bash
python -m app.cli.run_backtest \
  --universe-mode FIXED_UNIVERSE_RESEARCH \
  --start-date 2021-01-01 --end-date 2025-12-31 \
  --entry-model NEXT_OPEN --benchmark SPY \
  --output reports/backtest.json
```

API:

- `POST /api/v1/backtests?dry_run=true|false`
- `GET /api/v1/backtests`
- `GET /api/v1/backtests/{run_id}`
- `GET /api/v1/backtests/{run_id}/summary`
- `GET /api/v1/backtests/{run_id}/events`

## Reprodutibilidade e estatística

A configuração Pydantic completa é serializada em JSON canónico e identificada por SHA-256. O mesmo pedido produz o mesmo `config_hash`, `run_id`, sinais, scores e métricas quando os dados de entrada são iguais.

O resumo por horizonte inclui número de eventos, cobertura futura, média, mediana, taxa positiva, desvio-padrão, percentis, melhor/pior retorno e intervalo de confiança normal aproximado de 95%. Inclui ainda excesso contra o benchmark, buckets de score, agregações anual/trimestral e correlações exploratórias de características quando há pelo menos três outcomes completos. Amostras pequenas são identificadas explicitamente; não constituem validação estatística robusta.

## Limitações

- As barras Massive ajustadas tratam splits, mas não dividendos; retornos não são total return.
- O modelo não inclui slippage, comissões, impacto de mercado, halts ou delistings além do que estiver nos dados.
- `SIGNAL_CLOSE` é uma hipótese idealizada e pode ser inexequível após confirmação do fecho.
- Um universo fixo atual contém survivorship bias e não pode ser apresentado como backtest histórico do S&P 500.
- Correlações e intervalos de confiança são diagnósticos descritivos, não prova causal nem recomendação financeira.
