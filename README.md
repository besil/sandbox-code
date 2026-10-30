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

`sandbox-code` works in two phases: a **build** phase that generates an
inspectable `.sandbox-code/sandbox-run.sh`, and a **run** phase that just
executes it.

```bash
# First-time setup in a project: creates .sandbox-code/sandbox-init.sh and .sandbox-code/sandbox-run.sh
sandbox-code project init

# Configure features (rewrites .sandbox-code/sandbox-run.sh, rebuilds the image, runs init)
sandbox-code project build --github --whitelist

# Inspect exactly what is enabled
sandbox-code project features

# Run it (executes .sandbox-code/sandbox-run.sh)
sandbox-code
```

The generated `.sandbox-code/sandbox-run.sh` is a plain bash script — read it,
edit it, or run it directly with `bash .sandbox-code/sandbox-run.sh`.

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

## Commands

```
sandbox-code [command] [options]
```

Without a command, `sandbox-code` runs `.sandbox-code/sandbox-run.sh` (equivalent to
`sandbox-code run`).

| Command | Description |
|---|---|
| `run [options] [-- command...]` | Execute the generated `.sandbox-code/sandbox-run.sh` (default) |
| `project init` | Create `.sandbox-code/sandbox-init.sh` and an initial `.sandbox-code/sandbox-run.sh` |
| `project build [options] [-- command...]` | Generate/update `.sandbox-code/sandbox-run.sh`, build the image, and initialise the container |
| `project features` | List the features currently enabled for the workspace |
| `project clean` | Remove the container, init marker, generated files and their `.gitignore` entries |
| `host network blacklist` / `host network whitelist` | Apply firewall rules on the host |
| `host network clean` | Remove all firewall rules created by sandbox-code |
| `host network init-blacklist` / `host network init-whitelist` | Create a config template in the workspace |
| `version` | Print the OpenCode version |
| `reset` | Delete all persistent data (config, data, gitmirror) |

`run` is the default, so `sandbox-code`, `sandbox-code --bash` and
`sandbox-code -- npm test` are all short for `sandbox-code run ...`.

### `run` options

`run` executes `.sandbox-code/sandbox-run.sh`. By default it runs the command baked into that
script; you can override it per launch.

| Flag | Description |
|---|---|
| `-w`, `--workspace PATH` | Directory containing `.sandbox-code/sandbox-run.sh` (default: current directory) |
| `--bash` | Drop into an interactive bash shell instead of the configured command |
| `-- command...` | Override the command run inside the container for this launch |

```bash
sandbox-code run              # run the configured command (e.g. opencode .)
sandbox-code run --bash       # open a shell in the sandbox instead
sandbox-code run -- npm test  # run a one-off command
```

The init script always runs first, regardless of the override.

### `project build` options

`project build` is the only command that takes the feature flags. It writes them
into `.sandbox-code/sandbox-run.sh`, rebuilds the Docker image, and then runs the container
once with a no-op command to resolve the [init script](#init-script) up front —
so the first real `run` starts instantly. To change features, run it again.

| Flag | Description |
|---|---|
| `-w`, `--workspace PATH` | Directory to mount as `/workspace` (default: current directory) |
| `--no-cache` | Force a full Docker image rebuild without layer cache |
| `--ssh` | Mount `~/.ssh` (read-only). **Security: exposes your SSH private keys to the agent** — see [Credential exposure](#credential-exposure) |
| `--github` | Mount `~/.ssh` (read-only) and `~/.config/gh` (writable). **Security: exposes your SSH keys and GitHub token (rw) to the agent** |
| `--x11` | Mount X11 socket for clipboard support. **Security: grants the container access to the host display — not just the clipboard.** Usually unnecessary — see [Clipboard](#clipboard) |
| `--no-git` | Hide the real `.git`, exposing a disposable per-project repo |
| `--openspec` | Install the [OpenSpec](https://openspec.dev) CLI and run `openspec init --tools opencode` once on first container start (also enables the `openspec-planner` agent — see [OpenSpec](#openspec)) |
| `--no-init` | Skip the project init script entirely |
| `--init-script FILENAME` | Init script to run at container start, relative to workspace (default: `.sandbox-code/sandbox-init.sh`) |
| `--force-init` | Drop the per-project marker so the init script runs again on next launch |
| `--no-network` | Disable all networking (`--network none`) |
| `--network NAME` | Use a specific Docker network (default: bridge) |
| `--blacklist` | Isolate from local/Tailscale subnets, allow internet (`blacklist-networks.conf`) |
| `--whitelist` | Allow only listed CIDRs, block everything else (`whitelist-networks.conf`) |

`--no-network`, `--network`, `--blacklist` and `--whitelist` are mutually
exclusive.

Any arguments after `--` set the **default** command run inside the container:

```bash
sandbox-code project build -- npm test
sandbox-code                   # runs npm test
```

## Generated files

All generated files live in the hidden `.sandbox-code/` folder inside the workspace:

| File | Written by | Purpose |
|---|---|---|
| `sandbox-run.sh` | `project init`, `project build` | The full, inspectable `docker run` command (plus container reuse and init logic) |
| `sandbox-pre.sh` | `project build --blacklist` / `--whitelist` | Host-side firewall setup, run just before the container starts |
| `sandbox-post.sh` | `project build --blacklist` / `--whitelist` | Host-side firewall teardown, run when the container exits |
| `sandbox-cmd` | `run` | The command the container should run for the current launch (read at container start) |
| `sandbox-init.sh` | `project init` | Per-project init script template (edit it, or delete it for nothing extra) |

`project init` and `project build` also add `.sandbox-code/*` (and the negation
`!.sandbox-code/sandbox-init.sh`, so the init script stays committable) to the
workspace `.gitignore` (if not already listed).

Because `.sandbox-code/sandbox-run.sh` is a normal script, it is the single place to look when
debugging a launch. It accepts an optional argument to override the command run
inside the container:

```bash
bash .sandbox-code/sandbox-run.sh              # default command
bash .sandbox-code/sandbox-run.sh 'exec bash'  # shell instead
```

This is exactly what `sandbox-code run --bash` / `sandbox-code run -- cmd` do.
The chosen command is written to `.sandbox-code/sandbox-cmd`, which the container reads at
start — so an override also works when resuming an existing container.
`host network blacklist` / `host network whitelist` apply the same rules as the pre-hook,
but without launching a container.

## Persistent container

The container is **not removed** when you exit — it is stopped and reused on the next
launch. This keeps everything the [init script](#init-script) installed (Go, Java, Clojure,
project deps, …) so restarting the sandbox is instant instead of reinstalling packages.

- The container name is deterministic — **`sandbox-code-<workspace-folder-name>`**. When
  `.sandbox-code/sandbox-run.sh` runs, it resumes the container by name with `docker start`/`attach` if
  it exists, otherwise it creates a fresh one.
- Resuming re-runs the container's baked command, which reads `.sandbox-code/sandbox-cmd` — so
  `sandbox-code run --bash` / `-- cmd` take effect even on an existing container.
  Mount/feature flags (`--ssh`, `--github`, `--x11`, `--network`) are baked at build time;
  to change them, run `project build` again and clean the project.
- To start completely fresh (e.g. to pick up changes to mounts/flags, or re-run init
  from zero), clean the project instead:

  ```bash
  sandbox-code project clean
  ```

  (equivalent to `docker rm -f sandbox-code-<folder-name>` plus removing the
  generated `.sandbox-code/sandbox-run.sh`, `.sandbox-code/sandbox-pre.sh`,
  `.sandbox-code/sandbox-post.sh` and `.sandbox-code/sandbox-cmd` files, and
  their `.gitignore` entries).

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

The base image ships **without** language runtimes (Go, Java, Maven, Clojure). To give a project them, copy the [`sandbox-init.sh` template](/templates/sandbox-init.sh) from this repo into the project's `.sandbox-code/` folder as `.sandbox-code/sandbox-init.sh` and trim it to what the project needs. Projects **without** an init script get **nothing extra installed** — the lean base image is the default.

### Behaviour

1. On container start, `sandbox-code` checks whether an init script exists at `/workspace/<name>` (default: `.sandbox-code/sandbox-init.sh`).
2. If it exists, its content is hashed and compared against a stored marker at `/home/ubuntu/.local/share/opencode/.init-done/<workspace-hash>`.
3. If no marker exists **or** the init script content has changed, the script is run **as root** inside the container via `sudo`.
4. On success, the content hash is written to the marker file.
5. On subsequent launches, if the marker matches the current script content, the init step is skipped entirely — no repeated `npm install` or `apt-get`.

> The marker lives in the persistent `~/.config/sandbox-code/opencode-data/` volume, so it survives container restarts. Run `sandbox-code reset` to wipe all markers globally, or `sandbox-code project build --force-init` for a single project.

### Env vars

Because the script is **executed** as a subprocess (`sudo bash /workspace/.sandbox-code/sandbox-init.sh`) rather than sourced into the OpenCode process, `export` statements in it apply only to that run and are **not** visible to OpenCode or its child processes. Use it to install system packages and project dependencies; to pass an environment variable through to OpenCode, set it in the container command instead (e.g. `sandbox-code project build -- 'MY_VAR=value opencode .'`).

### Example custom `sandbox-init.sh`

```bash
#!/bin/bash
# Runs as root. Install system deps, project deps, and set env vars.

apt-get update && apt-get install -y --no-install-recommends libpq-dev
export DATABASE_URL="postgres://localhost:5432/myapp"
export DEBUG="1"

# Markers track content hash — this script only runs when its content changes.
```

Place the script in the project's `.sandbox-code/` folder, make it executable, and launch normally:

```bash
sandbox-code -w ~/projects/myapp
```

### CLI flags

The init-script flags live on `project build` (they are baked into `.sandbox-code/sandbox-run.sh`):

| Flag | Description |
|------|-------------|
| `--init-script FILENAME` | Custom init script filename relative to `/workspace` (default: `.sandbox-code/sandbox-init.sh`) |
| `--force-init` | Drop the per-project marker, forcing the init script to run again on the next launch |
| `--no-init` | Skip the init script entirely, even if it exists |

```bash
# Use a different filename
sandbox-code project build --init-script setup.sh

# Force re-run (e.g. after changing dependencies in the script)
sandbox-code project build --force-init

# Skip init entirely
sandbox-code project build --no-init
```

## OpenSpec

Pass `--openspec` to `project build` to set up [OpenSpec](https://openspec.dev) — spec-driven development — inside the sandbox:

```bash
sandbox-code project build --openspec
```

On the first container start (which happens during the build), `sandbox-code`:

1. Installs the OpenSpec CLI: `npm install -g @fission-ai/openspec@latest`.
2. Runs `openspec init --tools opencode` in `/workspace`, creating the `openspec/` folder and the `.opencode/` skills/commands (`/opsx-apply`, …).

Both steps are guarded by a marker in the persistent `opencode-data` volume, so they run **once per project**. They re-run when the container is recreated or with `--force-init`, and `project clean` removes the marker.

Because the install and `openspec init` need network access, `--openspec` is incompatible with `--no-network`.

### The `openspec-planner` agent

`--openspec` also relies on the [`opencode-2-openspec-plugin`](https://github.com/besil/opencode-2-openspec-plugin) plugin, which adds an **`openspec-planner`** primary agent (the "OpenSpec Architect"): it may write OpenSpec documents (`openspec/**`, `specs/**`, `project.md`, `AGENTS.md`) while keeping the rest of the codebase read-only, so planning never leaks into implementation. The plugin activates only when it detects an OpenSpec project.

The plugin and the agent's model are declared in the persistent OpenCode config (`config/opencode.jsonc` → `~/.config/sandbox-code/opencode-config/`). The `openspec-planner` agent is mapped to `openrouter/deepseek/deepseek-v4-pro` — a high-reasoning model, which OpenSpec recommends for planning. The plugin uses OpenCode V2's agent upsert, so the model declared under `agents.openspec-planner` is preserved.

> The OpenCode config is seeded **once**. If you already have a `~/.config/sandbox-code/opencode-config/opencode.jsonc`, the new `plugins`/`openspec-planner` entries are not added automatically — run `sandbox-code reset` or add them manually.

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
sandbox-code reset
```

> **Upgrading an existing install:** this sandbox now targets OpenCode V2, which reads `cli.json` (not the V1 `tui.json`) and uses the V2 `agents`/`plugins` config keys. Seeded config files are written only once, so delete the old files in `~/.config/sandbox-code/opencode-config/` (or run `sandbox-code reset`, which also clears stored credentials) and rebuild to pick up the new layout.

## Network isolation

Use `sandbox-code project build --blacklist` or `sandbox-code project build --whitelist` to bake
network restrictions into `.sandbox-code/sandbox-run.sh`. The build step also generates
`.sandbox-code/sandbox-pre.sh` (applies the firewall rules before the container starts) and
`.sandbox-code/sandbox-post.sh` (removes them when it exits), and creates the Docker network
if needed. Applying rules requires `sudo` on the host.

Both config files live in the workspace root. Create a starting template with:

```bash
sandbox-code host network init-blacklist   # or host network init-whitelist
```

| Mode | Config file | Behaviour |
|---|---|---|
| blacklist | `blacklist-networks.conf` | Block listed CIDRs, allow everything else |
| whitelist | `whitelist-networks.conf` | Allow only listed CIDRs, block everything else |

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

Apply or clean the rules on the host without launching a container:

```bash
sandbox-code host network blacklist     # apply the blacklist rules
sandbox-code host network whitelist     # apply the whitelist rules
sandbox-code host network clean         # remove all sandbox-code firewall rules
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
`.sandbox-code/sandbox-init.sh` installs (cached once per project by content hash). Use the
[`sandbox-init.sh` template](/templates/sandbox-init.sh) from this repo as a starting point,
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

Projects without a `.sandbox-code/sandbox-init.sh` get **nothing** extra installed.

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