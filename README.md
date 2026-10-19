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
| `--no-init` | Skip the project init script entirely (see [Init script](#init-script)) |
| `--init-script FILENAME` | Init script to run at container start, relative to workspace (default: `.sandbox-init.sh`) |
| `--force-init` | Delete the per-project marker so the init script runs again on next launch |
| `--ssh` | Mount `~/.ssh` into the container (read-only). **Security: exposes your SSH private keys to the agent** — see [Credential exposure](#credential-exposure) |
| `--github` | Mount `~/.ssh` (read-only) and `~/.config/gh` (writable). **Security: exposes your SSH keys and GitHub token (rw) to the agent** — see [Credential exposure](#credential-exposure) |
| `--x11` | Mount X11 socket for clipboard support. **Security: grants the container access to the host display — not just the clipboard.** Usually unnecessary — see [Clipboard](#clipboard) |
| `--no-network` | Disable all networking (`--network none`) |
| `--network NAME` | Use a specific Docker network (default: bridge) |
| `--blacklist` | Isolate from local/Tailscale subnets, allow internet (`blacklist-networks.conf`) |
| `--whitelist` | Allow only listed CIDRs, block everything else (`whitelist-networks.conf`) |
| `--clean-rules` | Remove firewall rules created by `--blacklist` / `--whitelist` |
| `--clean-project` | Remove this workspace's persisted container so the next launch starts completely fresh |
| `--no-git` | Hide the real `.git`, exposing a disposable per-project repo (keeps OpenCode sessions recoverable) |

Any arguments after `--` are run as a command inside the container.

## Persistent container

The container is **not removed** when you exit — it is stopped and reused on the next
launch. This keeps everything the [init script](#init-script) installed (Go, Java, Clojure,
project deps, …) so restarting the sandbox is instant instead of reinstalling packages.

- The container name is deterministic — **`sandbox-code-<workspace-folder-name>`**. On launch,
  `sandbox-code` resumes the container by name with `docker start` if it exists (running →
  attach, stopped → start), otherwise it creates a fresh one.
- Resuming re-runs the container's **original** command (e.g. `opencode .`). Flags like `--ssh`,
  `--github`, `--x11`, `--network` are applied when the container is first created; pass them the
  first time you launch in a project.
- To start completely fresh (e.g. to pick up changes to mounts/flags, or re-run init
  from zero), clean the project instead:

  ```bash
  sandbox-code --clean-project
  ```

  (equivalent to `docker rm -f sandbox-code-<folder-name>`).

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

## Init script

The container can run a project-specific initialisation script before OpenCode (or any other main command) starts. This is useful for installing project dependencies, setting environment variables, or any other setup that should happen once per project.

The base image ships **without** language runtimes (Go, Java, Maven, Clojure). To give a project them, copy the [`.sandbox-init.sh` template](/.sandbox-init.sh) from this repo into the project root and trim it to what the project needs. Projects **without** an init script get **nothing extra installed** — the lean base image is the default.

### Behaviour

1. On container start, `sandbox-code` checks whether an init script exists at `/workspace/<name>` (default: `.sandbox-init.sh`).
2. If it exists, its content is hashed and compared against a stored marker at `/home/ubuntu/.local/share/opencode/.init-done/<workspace-hash>`.
3. If no marker exists **or** the init script content has changed, the script is run **as root** inside the container via `sudo`.
4. On success, the content hash is written to the marker file.
5. On subsequent launches, if the marker matches the current script content, the init step is skipped entirely — no repeated `npm install` or `apt-get`.

> The marker lives in the persistent `~/.config/sandbox-code/opencode-data/` volume, so it survives container restarts. Run `sandbox-code --reset` to wipe all markers globally, or use `--force-init` for a single project.

### Env vars

Because the script is **sourced** (`. /workspace/.sandbox-init.sh`) rather than executed as a subprocess, any `export` statements in the script are visible to OpenCode and all child processes.

### Example custom `.sandbox-init.sh`

```bash
#!/bin/bash
# Runs as root. Install system deps, project deps, and set env vars.

apt-get update && apt-get install -y --no-install-recommends libpq-dev
export DATABASE_URL="postgres://localhost:5432/myapp"
export DEBUG="1"

# Markers track content hash — this script only runs when its content changes.
```

Place the script in your project root, make it executable, and launch normally:

```bash
sandbox-code -w ~/projects/myapp
```

### CLI flags

| Flag | Description |
|------|-------------|
| `--init-script FILENAME` | Custom init script filename relative to `/workspace` (default: `.sandbox-init.sh`) |
| `--force-init` | Delete the per-project marker, forcing the init script to run again on the next launch |
| `--no-init` | Skip the init script entirely, even if it exists |

```bash
# Use a different filename
sandbox-code --init-script setup.sh

# Force re-run (e.g. after changing dependencies in the script)
sandbox-code --force-init

# Skip init entirely
sandbox-code --no-init
```

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

The base image ships only what OpenCode needs to run (Node.js) plus universal system
tools. Language runtimes, browsers, and optional utilities are **not** baked in —
install them per project via the [init script](#init-script).

| Tool | Version |
|---|---|
| Ubuntu | 26.04 |
| Node.js | 22 LTS |
| Python | 3.14 |
| GitHub CLI | ✓ |
| build-essential | ✓ |
| git, curl, wget, vim, jq | ✓ |
| OpenCode | latest |

### Optional packages on demand

There is **no** built-in default installer — a project gets exactly what its own
`.sandbox-init.sh` installs (cached once per project by content hash). Use the
[`.sandbox-init.sh` template](/.sandbox-init.sh) from this repo as a starting point,
or these snippets inside a custom per-project init script:

| Package | Init script snippet |
|---|---|
| Go | `apt-get install -y golang` |
| Java / Maven | `apt-get install -y temurin-26-jdk maven` |
| Clojure | `curl -L -O https://github.com/clojure/brew-install/releases/latest/download/linux-install.sh && chmod +x linux-install.sh && ./linux-install.sh` |
| Chromium (headless) | `apt-get install -y chromium-browser` (⚠ Ubuntu's pkg is a snap wrapper that may not run inside a container; fallback: `npx playwright install --with-deps chromium`) |
| PDF utils | `apt-get install -y poppler-utils` |
| Network diagnostics | `apt-get install -y gping bind9-dnsutils iproute2 iputils-ping` |
| Clipboard | `apt-get install -y xclip xsel` |
| Readline wrapper | `apt-get install -y rlwrap` |

Projects without a `.sandbox-init.sh` get **nothing** extra installed.

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