FROM ubuntu:26.04

ENV DEBIAN_FRONTEND=noninteractive \
    NODE_MAJOR=22

RUN apt-get update && apt-get install -y \
    curl wget git vim jq unzip \
    build-essential \
    ca-certificates gnupg lsb-release \
    python3 python3-pip python3-venv \
    maven \
    && rm -rf /var/lib/apt/lists/*

RUN wget -qO - https://packages.adoptium.net/artifactory/api/gpg/key/public | gpg --dearmor -o /usr/share/keyrings/adoptium-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/adoptium-archive-keyring.gpg] https://packages.adoptium.net/artifactory/deb $(lsb_release -cs) main" > /etc/apt/sources.list.d/adoptium.list \
    && apt-get update && apt-get install -y temurin-26-jdk \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deb.nodesource.com/setup_${NODE_MAJOR}.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y docker-ce-cli docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | gpg --dearmor -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y gh \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g opencode-ai

RUN useradd -m -s /bin/bash sandbox && echo "sandbox ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers \
    && mkdir -p /home/sandbox/.config/opencode /home/sandbox/.local/share/opencode \
    && chown -R sandbox:sandbox /home/sandbox/.config /home/sandbox/.local

USER sandbox
WORKDIR /workspace

ENTRYPOINT ["/bin/bash"]