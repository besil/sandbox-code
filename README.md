# sandbox-code

Dockerised development sandbox running [OpenCode](https://opencode.ai) inside an isolated Ubuntu container. The agent has full access inside the container but cannot touch your host system — only the workspace directory you explicitly mount.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/)

## Installation

```bash
git clone https://github.com/your-org/sandbox-code.git ~/sandbox-code
chmod +x ~/sandbox-code/sandbox-code

# Add to PATH (zsh)
echo 'export PATH="$HOME/sandbox-code:$PATH"' >> ~/.zshrc
source ~/.zshrc

# Or for bash
echo 'export PATH="$HOME/sandbox-code:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

## Quick start

```bash
# Launch OpenCode in the current directory
sandbox-code

# Mount a specific project and open a bash shell
sandbox-code -w ~/my-project --bash

# Run a command inside the sandbox
sandbox-code -- npm test
```

## API keys

Set any of these environment variables in your host shell (`~/.zshrc`, `~/.bashrc`, or inline):

```bash
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
export DEEPSEEK_API_KEY="sk-..."
export OPENROUTER_API_KEY="sk-or-..."
export GOOGLE_API_KEY="..."
export ZAI_API_KEY="zai-..."
export OPENCODE_API_KEY="..."
```

Keys are forwarded to the container automatically. Alternatively, you can run `/connect` inside OpenCode — keys stored this way persist across restarts (see [Persistent data](#persistent-data)).

## Options

```
sandbox-code [options] [-- command...]
```

| Flag | Description |
|---|---|
| `-w`, `--workspace PATH` | Directory to mount as `/workspace` (default: current directory) |
| `--bash` | Start an interactive bash shell instead of OpenCode |
| `--version` | Print OpenCode version and exit |
| `--ssh` | Mount `~/.ssh` into the container (read-only) |
| `--github` | Mount `~/.ssh` (read-only) and `~/.config/gh` (writable) |
| `--x11` | Mount X11 socket for clipboard support (enables copy/paste) |
| `--no-network` | Disable all networking (`--network none`) |
| `--network NAME` | Use a specific Docker network (default: bridge) |
| `--blacklist` | Isolate from local/Tailscale subnets, allow internet (`blacklist-networks.conf`) |
| `--whitelist` | Allow only listed CIDRs, block everything else (`whitelist-networks.conf`) |
| `--clean-rules` | Remove firewall rules created by `--blacklist` / `--whitelist` |
| `--no-git` | Hide `.git` directory (tmpfs over `/workspace/.git`) |
| `--reset` | Delete all persistent data before starting |
| `--no-cache` | Force a full Docker image rebuild without layer cache |

Any arguments after `--` are run as a command inside the container.

## Persistent data

OpenCode configuration and stored credentials survive container restarts:

```
~/.config/sandbox-code/
├── opencode-config/   → /home/sandbox/.config/opencode
└── opencode-data/     → /home/sandbox/.local/share/opencode
```

To wipe everything and start fresh:

```bash
sandbox-code --reset
```

## Network isolation

Use `--blacklist` or `--whitelist` to restrict outbound traffic from the container.
Both require `sudo` to apply iptables/nftables rules on the host.

| Flag | Config file | Behaviour |
|---|---|---|
| `--blacklist` | `blacklist-networks.conf` | Block listed CIDRs, allow everything else |
| `--whitelist` | `whitelist-networks.conf` | Allow only listed CIDRs, block everything else |

Config file format (first two lines = Docker network name + subnet, rest = CIDRs):

```
sandbox-code-blacklist
172.30.0.0/16
# comments start with #
10.0.0.0/8
192.168.0.0/16
100.64.0.0/10
```

Clean up firewall rules:

```bash
sandbox-code --clean-rules
```

## Image contents

| Tool | Version |
|---|---|
| Ubuntu | 26.04 |
| Node.js | 22 LTS |
| Python | 3.14 |
| JDK (Temurin) | 26 |
| Maven | 3.9 |
| GitHub CLI | ✓ |
| Chromium (headless) | ✓ |
| git, curl, wget, vim, jq | ✓ |
| OpenCode | latest |

## Using in other projects

The `sandbox-code:latest` image can be added directly to any `docker-compose.yml`:

```yaml
services:
  sandbox:
    image: sandbox-code:latest
    stdin_open: true
    tty: true
    volumes:
      - .:/workspace
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
```