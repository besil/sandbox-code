FROM ubuntu:26.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    curl wget git vim jq unzip \
    build-essential \
    ca-certificates gnupg lsb-release \
    python3 python3-pip python3-venv \
    maven \
    && rm -rf /var/lib/apt/lists/*

RUN wget -qO - https://packages.adoptium.net/artifactory/api/gpg/key/public | gpg --dearmor -o /usr/share/keyrings/adoptium-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/adoptium-archive-keyring.gpg] https://packages.adoptium.net/artifactory/deb $(lsb_release -cs) main" > /etc/apt/sources.list.d/adoptium.list \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | gpg --dearmor -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y \
    nodejs \
    temurin-26-jdk \
    gh \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g opencode-ai

RUN mkdir -p /home/ubuntu/.config/opencode /home/ubuntu/.local/share/opencode && \
    chown -R ubuntu:ubuntu /home/ubuntu/.config /home/ubuntu/.local && \
    echo "PS1='\[\033[01;35m\]\u@\h\[\033[00m\]:\[\033[01;33m\]\w\[\033[00m\]\\\$ '" >> /home/ubuntu/.bashrc

USER ubuntu
WORKDIR /workspace

ENTRYPOINT ["/bin/bash"]