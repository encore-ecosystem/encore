FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ARG UBUNTU_MIRROR=http://archive.ubuntu.com/ubuntu

RUN sed -i \
        -e "s|http://archive.ubuntu.com/ubuntu|${UBUNTU_MIRROR}|g" \
        -e "s|http://security.ubuntu.com/ubuntu|${UBUNTU_MIRROR}|g" \
        /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get -o Acquire::Retries=5 update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        clang \
        curl \
        file \
        git \
        libbrotli-dev \
        libclang-rt-18-dev \
        libssl-dev \
        libzstd-dev \
        lld \
        llvm \
        openssl \
        unzip \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
COPY . .

RUN mkdir -p /opt/encore/bin
COPY --from=compiler_seed encore /opt/encore/bin/encore
RUN chmod +x /opt/encore/bin/encore

CMD ["scripts/test-ci-local.sh", "/opt/encore/bin/encore"]
