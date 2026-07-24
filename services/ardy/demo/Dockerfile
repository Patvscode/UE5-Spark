FROM ue5-spark-ardy:0.4.0-open-text

LABEL org.opencontainers.image.title="UE5-Spark ARDY interactive motion lab"

RUN python -m pip install --no-cache-dir "/opt/ardy[demo]" \
    && mkdir -p \
        /opt/ardy/.cache \
        /opt/ardy/datasets/bones-seed/cache \
        /opt/ardy/outputs \
    && chmod -R a+rX /opt/ardy

RUN python -c "from viser import _client_autobuild; _client_autobuild.ensure_client_is_built()"

WORKDIR /opt/ardy
ENV CHECKPOINTS_DIR=/models \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "scripts/run_demo.py"]
CMD ["--no-compile"]
