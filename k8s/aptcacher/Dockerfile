FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y --no-install-recommends wget gnupg ca-certificates && \
    apt-get download apt-cacher-ng && \
    dpkg --force-not-root --force-all -i apt-cacher-ng*.deb || true && \
    rm -rf /var/lib/apt/lists/* && \
    rm -f /etc/init.d/apt-cacher-ng && \
    rm -f /etc/systemd/system/multi-user.target.wants/apt-cacher-ng.service

EXPOSE 3142

CMD ["apt-cacher-ng", "-f"]