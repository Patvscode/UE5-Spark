FROM nvcr.io/nvidia/pytorch:25.05-py3

ARG ARDY_COMMIT=693f74d13b3d04a0a22ce127ee79c929dd89756b
LABEL org.opencontainers.image.title="UE5-Spark ARDY pose service" \
      org.opencontainers.image.source="https://github.com/Patvscode/UE5-Spark" \
      org.opencontainers.image.licenses="MIT AND Apache-2.0"

RUN git clone --filter=blob:none https://github.com/nv-tlabs/ardy.git /opt/ardy \
    && git -C /opt/ardy checkout --detach "${ARDY_COMMIT}" \
    && python -m pip install --no-cache-dir /opt/ardy

COPY service /opt/ue5-spark-ardy
COPY --from=motion_config motion-catalog.json /opt/ue5-spark-ardy/motion-catalog.json
# Release snapshots are intentionally extracted with owner-only permissions.
# Normalize copied runtime files so the deliberately unprivileged container
# user can import and execute the service without weakening host permissions.
RUN chmod -R a+rX /opt/ue5-spark-ardy
WORKDIR /opt/ue5-spark-ardy
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HOME=/tmp/huggingface \
    HOME=/tmp/home TRITON_CACHE_DIR=/tmp/triton
ENTRYPOINT ["python", "/opt/ue5-spark-ardy/ardy_pose_service.py"]
CMD ["--host", "127.0.0.1", "--port", "8777", "--provider", "mock"]
