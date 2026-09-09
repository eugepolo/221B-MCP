FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir '.[sherlock]' \
    && useradd --create-home --uid 10001 baker \
    && mkdir /data \
    && chown baker:baker /data

USER baker
ENV PYTHONUNBUFFERED=1 MCP_221B_DATA_DIR=/data
ENTRYPOINT ["221b-mcp"]
CMD ["serve"]
