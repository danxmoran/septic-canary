# Image based off template here:
# https://github.com/tiangolo/full-stack-fastapi-postgresql/blob/master/{{cookiecutter.project_slug}}/backend/backend.dockerfile

FROM tiangolo/uvicorn-gunicorn-fastapi:python3.9

WORKDIR /app/

# Install poetry.
RUN curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/master/install-poetry.py | POETRY_HOME=/opt/poetry python && \
    cd /usr/local/bin && \
    ln -s /opt/poetry/bin/poetry && \
    poetry config virtualenvs.create false

# Add project files.
COPY ./pyproject.toml ./poetry.lock /app/
COPY ./septic_canary /app/septic_canary

ENV PYTHONPATH=/app
ENV MODULE_NAME=septic_canary.main
