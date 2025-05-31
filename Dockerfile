FROM python:3.12-bullseye AS builder

ENV PYTHONUNBUFFERED 1
ENV PYTHONDONTWRITEBYTECODE 1

WORKDIR /code

RUN pip install poetry==1.8.3 && \
    poetry config virtualenvs.in-project true && \
    poetry config virtualenvs.create true

COPY pyproject.toml poetry.lock ./

RUN poetry install --only main --no-root

FROM python:3.12-slim-bullseye AS runtime

ENV PYTHONUNBUFFERED 1
ENV PYTHONDONTWRITEBYTECODE 1

WORKDIR /code

ENV PYTHONPATH=/code
ENV VIRTUAL_ENV=/code/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

COPY --from=builder ${VIRTUAL_ENV} ${VIRTUAL_ENV}

COPY alembic.ini .
COPY alembic ./alembic

COPY ./smt /code/smt
