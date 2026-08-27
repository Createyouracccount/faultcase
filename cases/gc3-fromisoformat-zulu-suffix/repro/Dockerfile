FROM python:3.10-slim@sha256:a78e4529630cfe8c5199cafd6e0c28ee1579a13f86274396d8b6b2d80367aa3a

ENV PYTHONHASHSEED=0 \
    TZ=UTC \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /bundle
COPY uv-bootstrap.lock requirements.lock ./
RUN pip install --no-cache-dir --require-hashes --no-deps -r uv-bootstrap.lock \
 && uv pip install --system --no-cache --no-deps --require-hashes -r requirements.lock

COPY . .
RUN useradd -m runner && chown -R runner /bundle
USER runner

ENV FAULTCASE_OBSERVED=/tmp/observed_signature.json
CMD ["python", "failing_test.py"]
