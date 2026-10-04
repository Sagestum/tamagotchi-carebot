FROM python:3.13-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev make && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY Makefile ./
COPY src ./src
RUN make

FROM python:3.13-slim
WORKDIR /app
COPY --from=build /app/libtama.so ./
COPY server.py tama.py carebot.py growth.py report.py ./
COPY web ./web
COPY tama/tama.b ./tama/tama.b
RUN useradd -u 1000 -m tama && mkdir /data && chown tama /data
USER tama
VOLUME /data
EXPOSE 8137
# SIGINT makes server.py save the state before it exits
STOPSIGNAL SIGINT
CMD ["python3", "-u", "server.py", "--host", "0.0.0.0", "--port", "8137", "--state", "/data/tama_state.json"]
