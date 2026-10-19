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
| `--version` | Print OpenCode version and exit |
| `--reset` | Delete all persistent data before starting (config, data, gitmirror) |
| `--no-cache` | Force a full Docker image rebuild without layer cache |
| `--bash` | Start an interactive bash shell instead of OpenCode |
| `--ssh` | Mount `~/.ssh` into the container (read-only). **Security: exposes your SSH private keys to the agent** — see [Credential exposure](#credential-exposure) |
| `--github` | Mount `~/.ssh` (read-only) and `~/.config/gh` (writable). **Security: exposes your SSH keys and GitHub token (rw) to the agent** — see [Credential exposure](#credential-exposure) |
| `--x11` | Mount X11 socket for clipboard support. **Security: grants the container access to the host display — not just the clipboard.** Usually unnecessary — see [Clipboard](#clipboard) |
| `--no-network` | Disable all networking (`--network none`) |
| `--network NAME` | Use a specific Docker network (default: bridge) |
| `--blacklist` | Isolate from local/Tailscale subnets, allow internet (`blacklist-networks.conf`) |
| `--whitelist` | Allow only listed CIDRs, block everything else (`whitelist-networks.conf`) |
| `--clean-rules` | Remove firewall rules created by `--blacklist` / `--whitelist` |
| `--no-git` | Hide the real `.git`, exposing a disposable per-project repo (keeps OpenCode sessions recoverable) |

Any arguments after `--` are run as a command inside the container.

## Credential exposure

**`--ssh` and `--github` punch holes in the sandbox by mounting real credentials from your host.** Any process inside the container — including the agent and anything it runs — can read them:

- **`--ssh`** mounts `~/.ssh` read-only. Read-only does **not** prevent use or exfiltration: the agent can read your SSH private keys and authenticate to every host you have access to.
- **`--github`** mounts `~/.ssh` (read-only) **and** `~/.config/gh` **writable**, which holds your GitHub auth token. The agent can read the token and modify the `gh` configuration.

With outbound networking (the default bridge), these credentials can be exfiltrated — e.g. via prompt injection from untrusted files, issues, or web content the agent processes. Use these flags only when strictly needed, prefer scoped deploy keys and minimal-scope tokens, and combine with `--no-network` or `--whitelist` when working on untrusted input.

## Clipboard

`--x11` exists **only** to share the clipboard, but it grants the container access to the host **display**, not just the clipboard (keylogging, screen capture, input injection into other apps). For copy/paste it is usually unnecessary, because OpenCode's clipboard does not need X11:

- **OSC 52 (no X, no mount).** OpenCode's TUI emits an OSC 52 escape on every copy; your terminal emulator receives it and sets the host clipboard.
- **Terminal-native selection.** The TUI captures the mouse, but holding **Shift** hands the mouse back to the terminal so you can select and copy with the terminal's own shortcut. Confirmed working in **lxterminal**: Shift+drag to select, then `Ctrl+Shift+C` (paste: `Ctrl+Shift+V`, or middle-click for the primary selection).
- **Pasting into OpenCode** is just the terminal's paste (`Ctrl+Shift+V`); it never needs `--x11`.

OSC 52 terminal support:

| Terminal | OSC 52 |
|---|---|
| kitty, alacritty, wezterm, foot, Ghostty, Windows Terminal, iTerm2 (enable in preferences) | yes |
| VTE-based: lxterminal, GNOME Terminal, XFCE Terminal, Terminator | no — use Shift+selection instead |

Through tmux, OSC 52 additionally needs `set -g set-clipboard on` (and `set -g allow-passthrough on` on tmux ≥ 3.3).

`--x11` is therefore effectively only needed if you specifically rely on `xclip`/`xsel` **inside** the container. Otherwise prefer the alternatives above to keep the host display out of the sandbox.

## Persistent data

OpenCode configuration and stored credentials survive container restarts:

```
~/.config/sandbox-code/
├── opencode-config/   → /home/ubuntu/.config/opencode
├── opencode-data/     → /home/ubuntu/.local/share/opencode
└── gitmirror/         → disposable per-workspace git repos (used by --no-git)
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
sandbox-code-caged
172.30.0.0/16
# comments start with #
10.0.0.0/8
172.16.0.0/12
192.168.0.0/16
100.64.0.0/10
169.254.0.0/16
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
| Go | ✓ |
| GitHub CLI | ✓ |
| Chromium (headless) | ✓ |
| build-essential, poppler-utils | ✓ |
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