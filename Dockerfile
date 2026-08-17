# 9front all-in-one (cpu+fs+auth) under QEMU/TCG.
# No KVM on Orchard pods, so this is pure emulation -- fine for 9front.

FROM alpine:3.21

RUN apk add --no-cache \
    qemu-system-x86_64 \
    curl \
    socat

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# rcpu, 9p/exportfs, auth ticket service
EXPOSE 17019 564 567

ENTRYPOINT ["/entrypoint.sh"]
