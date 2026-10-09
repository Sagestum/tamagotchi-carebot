FROM python:3.13-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev make && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY Makefile ./
COPY src ./src
RUN make

FROM python:3.13-slim
WORKDIR /app
COPY --from=build /app/libtama.so ./
COPY server.py engine.py tama.py carebot.py carebot_umino.py carebot_mothra.py carebot_tamaotch.py growth.py growth_angel.py growth_morino.py growth_umino.py growth_mothra.py growth_genjin.py models.py report.py ./
COPY web ./web
RUN useradd -u 1000 -m tama && mkdir /data && chown tama /data
USER tama
VOLUME /data
EXPOSE 8137
# The ROM is not in the image: it is asked for in the browser and kept in /data
# SIGINT makes server.py save the state before it exits
STOPSIGNAL SIGINT
CMD ["python3", "-u", "server.py", "--host", "0.0.0.0", "--port", "8137", "--state", "/data/tama_state.json"]
