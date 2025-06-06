FROM python:3.12-bullseye AS builder

ENV PYTHONUNBUFFERED 1
ENV PYTHONDONTWRITEBYTECODE 1

WORKDIR /code

ARG INSTALL_DEV=false

RUN pip install poetry==2.1.3 && \
    poetry config virtualenvs.in-project true && \
    poetry config virtualenvs.create true

COPY pyproject.toml poetry.lock ./

RUN if [ "$INSTALL_DEV" = "true" ]; then \
    poetry install --no-root; \
    else \
    poetry install --no-root --without dev; \
    fi

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
