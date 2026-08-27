# 9front all-in-one (cpu+fs+auth) under QEMU.
# Uses KVM when /dev/kvm is present, otherwise falls back to pure emulation --
# fine for 9front, and what Orchard pods get.

FROM alpine:3.21

RUN apk add --no-cache \
    qemu-system-x86_64 \
    qemu-img \
    python3 \
    curl \
    socat

COPY docker/vm.py docker/supervise.py docker/provision.py /opt/9front/
COPY docker/entrypoint.sh /entrypoint.sh
COPY docker/9health /usr/local/bin/9health
# Same script as the local dev setup; talks to the console the supervisor
# exposes, so `docker exec -it <c> 9console run 'ps'` drives the machine.
COPY console.py /usr/local/bin/9console
RUN chmod +x /entrypoint.sh /usr/local/bin/9console /usr/local/bin/9health

# Where the console socket, log and input fifo live. 9console reads this too.
ENV RUN=/run/9front
ENV DISK_PATH=/data/9front.qcow2
VOLUME /data

# rcpu (the cpu service), tls 9fs, auth ticket service
EXPOSE 17019 17020 567

# 9front needs to flush hjfs on the way down; give fshalt room to finish.
STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=3 \
    CMD ["/usr/local/bin/9health"]

ENTRYPOINT ["/entrypoint.sh"]
