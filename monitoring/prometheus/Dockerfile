FROM prom/prometheus:v3.13.0

COPY prometheus.yml /etc/prometheus/prometheus.yml

RUN promtool check config /etc/prometheus/prometheus.yml
