# Contributing

## Setup

```sh
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev,mcp]"
```

## Running tests

```sh
python -m pytest tests -q
```

## Full local check

```sh
bash scripts/verify.sh
```

## Design rule

Aphrodite must not modify the external Hermes core. Integrate only through supported boundaries: plugin APIs, Discord interactions and webhooks, FastAPI routes, static files, cron or systemd jobs, and SQLite or filesystem state.

## Private overlay

Never commit `.local/`, real `config/aphrodite.env`, or real Discord IDs. For local development, copy `config/aphrodite.env.example` to `config/aphrodite.env` and fill it with local values outside version control.
