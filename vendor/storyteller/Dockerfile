FROM python:3.12-slim
WORKDIR /app
COPY packages/service /app/service
RUN pip install --no-cache-dir /app/service
# config, brief and data are mounted at /config and /data
ENV STORYTELLER_CONFIG=/config/storyteller.yaml
VOLUME ["/data"]
EXPOSE 8787
CMD ["storyteller", "serve", "--config", "/config/storyteller.yaml", "--port", "8787"]
