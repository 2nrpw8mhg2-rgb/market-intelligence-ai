# Market Intelligence AI

Plataforma de investigação quantitativa para analisar dados históricos do mercado acionista norte-americano, testar hipóteses e identificar condições mensuráveis. O projeto não produz aconselhamento financeiro nem executa ordens.

A Fase 3 contém a fundação técnica, persistência OHLCV idempotente, universos point-in-time, calendário oficial XNYS, validação de completude por sessão, Feature Engine determinístico e um endpoint de desenvolvimento para consultar features armazenadas. Scanner, ranking, backtesting, ML e trading ainda não estão implementados.

## Arquitetura

O repositório é um monorepo simples para manter o frontend Lovable separado do backend quantitativo:

```text
.
├── src/                         # frontend Lovable / TanStack Start
├── backend/
│   ├── app/
│   │   ├── api/                 # rotas finas e tratamento HTTP
│   │   ├── core/                # settings e logging estruturado
│   │   ├── database/            # engine, sessões e metadata SQLAlchemy
│   │   ├── models/              # modelos persistentes
│   │   ├── schemas/             # contratos Pydantic
│   │   ├── market_data/         # interface e provider Massive
│   │   ├── services/            # futura orquestração de casos de uso
│   │   ├── features/            # motor vetorizado de features
│   │   ├── patterns/            # fronteira reservada
│   │   ├── strategies/          # fronteira reservada
│   │   ├── backtesting/         # fronteira reservada
│   │   ├── ranking/             # fronteira reservada
│   │   ├── risk/                # fronteira reservada
│   │   └── ml/                  # fronteira reservada; sem ML nesta fase
│   ├── alembic/                 # migrações PostgreSQL
│   ├── tests/                   # testes unitários e de API
│   ├── Dockerfile
│   └── pyproject.toml
├── .env.example
└── docker-compose.yml
```

Fluxo pretendido nas fases seguintes:

```text
Market Data → Data Processing → Feature Engine → Pattern Detection
→ Strategy Engine → Backtesting → Ranking → FastAPI → Frontend
```

Os endpoints apenas validam e coordenam. A lógica de fornecedores, features e estratégias vive fora da camada HTTP. `MarketDataProvider` permite trocar ou combinar Massive, Alpaca e outros fornecedores sem alterar os consumidores.

## Requisitos

- Docker e Docker Compose (caminho recomendado), ou
- Python 3.12+ e PostgreSQL 15+
- Node.js para desenvolver o frontend existente

## Configuração

Crie o ficheiro local de ambiente. Nunca versionar `.env`.

```bash
cp .env.example .env
```

Variáveis atuais:

| Variável | Descrição |
| --- | --- |
| `MASSIVE_API_KEY` | Chave da Massive; obrigatória para chamadas reais |
| `DATABASE_URL` | URL SQLAlchemy assíncrona do PostgreSQL |
| `ENVIRONMENT` | Ambiente, por exemplo `development` ou `production` |
| `LOG_LEVEL` | Nível de logging |

`ALPACA_API_KEY`, `ALPACA_SECRET_KEY` e `OPENAI_API_KEY` estão apenas reservadas. Não são usadas nesta fase.

## Executar com Docker

```bash
docker compose up --build -d db
docker compose run --rm api alembic upgrade head
docker compose up --build api
```

API: <http://localhost:8000>

OpenAPI: <http://localhost:8000/docs>

Health: <http://localhost:8000/health>

## Executar o backend localmente

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
alembic upgrade head
uvicorn app.main:app --reload
```

O `DATABASE_URL` local típico é:

```text
postgresql+asyncpg://market_ai:market_ai@localhost:5432/market_ai
```

## Executar testes

Os testes Massive usam transporte HTTP simulado: não consomem a API nem precisam de uma chave real.

```bash
cd backend
pytest --cov=app --cov-report=term-missing
```

## Endpoints disponíveis

### `GET /health`

```json
{
  "status": "ok",
  "service": "market-intelligence-api",
  "version": "0.3.0",
  "environment": "development"
}
```

### `GET /api/v1/features/{ticker}`

Lê apenas as barras já armazenadas, calcula as features e devolve warm-ups como `null`. Não obtém dados da Massive e não constitui uma análise ou recomendação.

Parâmetros opcionais: `start_date` e `end_date`, em formato `YYYY-MM-DD`.

```bash
curl 'http://localhost:8000/api/v1/features/AAPL?start_date=2024-01-01&end_date=2024-12-31'
```

## Massive Market Data

`MassiveMarketDataProvider.get_daily_bars(ticker, start_date, end_date)` obtém OHLCV diário ajustado e ascendente para um único ticker. A implementação inclui:

- paginação por `next_url`;
- timeout configurável;
- retries exponenciais para falhas de rede e HTTP 5xx;
- respeito por `Retry-After` em HTTP 429;
- erros tipados para autenticação, rate limit e payload inválido;
- validação Pydantic e logging sem credenciais.

`MarketDataService` coordena provider, calendário XNYS, validação, normalização UTC e persistência. A completude é calculada pelas sessões reais da bolsa: fins de semana e feriados não são lacunas, enquanto sessões ausentes são pedidas ao provider em intervalos mínimos. A persistência usa `ON CONFLICT DO UPDATE`; reprocessar a mesma barra atualiza os valores e não cria duplicados.

## Base de dados

As duas migrações criam:

- `symbols`
- `market_bars`
- `features`
- `opportunities`
- `strategies`
- `backtest_runs`
- `backtest_trades`
- `universes`
- `universe_memberships`
- `securities`

A identidade de uma barra é `ticker + timestamp + timeframe + provider`, materializada através de `symbol_id` e de uma constraint única PostgreSQL. Os universos guardam `valid_from`, `valid_to`, `source` e `loaded_at`, permitindo consultas point-in-time. `securities` fornece uma identidade estável opcional separada do ticker. Valores monetários usam `NUMERIC`; timestamps são timezone-aware.

## Feature Engine

O motor recebe OHLCV cronológico e devolve o mesmo `DataFrame` com SMA 20/50/200, EMA 20, RSI 14, MACD, ATR 14, retornos, volume relativo, máximos/mínimos anteriores, volatilidade e momentum. As fórmulas, warm-ups e políticas de qualidade estão em [backend/docs/FEATURES.md](backend/docs/FEATURES.md).

Premissas de dados, calendário, S&P 500, corporate actions e alterações de ticker estão em [backend/docs/MARKET_DATA.md](backend/docs/MARKET_DATA.md).

Máximos e mínimos anteriores usam sempre `shift(1)` antes da janela. A sessão atual nunca entra no limiar contra o qual é comparada.

## Frontend

O frontend continua ligado ao [projeto Lovable](https://lovable.dev/projects/cd4a898c-798d-43c2-b215-a22da86e3bb0).

```bash
npm install
npm run dev
```

## Limitações atuais

- Não existe scanner, ranking, backtesting, ML ou trading.
- Ainda não existe endpoint público de ingestão; a ingestão é um serviço interno para que autenticação e limites operacionais sejam definidos antes da exposição HTTP.
- A disponibilidade e profundidade histórica dependem do plano Massive.
- O schema e importador suportam composição point-in-time do S&P 500, mas nenhuma fonte histórica é fabricada ou distribuída. É necessário carregar uma fonte autorizada.
- XNYS identifica sessões de mercado, mas não explica suspensões, halts ou períodos fora da vida de uma security.
- As barras Massive atuais são ajustadas para splits, mas não para dividendos.

## Próxima fase recomendada

Após aprovação da Fase 3: selecionar/carregar uma fonte histórica autorizada do S&P 500 e definir políticas para gaps específicos de cada security. Só depois implementar o scanner `BREAKOUT_20D_VOLUME`, com configuração versionada e testes de look-ahead. Backtesting continua fora desta fase.
