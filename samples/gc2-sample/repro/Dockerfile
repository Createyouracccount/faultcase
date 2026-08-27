FROM python:3.11-slim@sha256:9c900dea9e8fb7e16277c179b555cc72d29a352dbc33cff48ad5a0412fd5bfc7

ENV PYTHONHASHSEED=0 \
    TZ=UTC \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /bundle
COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes --no-deps -r requirements.lock

COPY . .
RUN useradd -m runner && chown -R runner /bundle
USER runner

ENV FAULTCASE_OBSERVED=/tmp/observed_signature.json
CMD ["python", "failing_test.py"]
