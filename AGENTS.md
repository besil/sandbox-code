# AGENTS.md

## Repo overview

Dockerised OpenCode sandbox. No build/test/lint pipeline — this is an infrastructure project.

## Repo layout

```
sandbox-code.py / sandbox-code / Dockerfile   # the tool itself
templates/                                     # files users copy into their own workspace
  └── .sandbox-init.sh
config/                                        # the tool's own runtime configuration
  ├── opencode.jsonc
  ├── cli.json
  └── firewall/
      ├── blacklist-networks.conf
      └── whitelist-networks.conf
```

`templates/` holds starting points users copy (seeded/copied into a workspace);
`config/` holds the tool's own defaults (seeded into the persistent OpenCode config
volume and copied into the image). Keep the two separate when adding files.

## Architecture

```
sandbox-code (shell wrapper) → sandbox-code.py (Python) → bash .sandbox-run.sh → docker run
```

- `sandbox-code` is a bash `exec` wrapper that finds `sandbox-code.py` relative to itself, then delegates.
- `sandbox-code.py` has two phases: **`project build`** writes an inspectable `.sandbox-run.sh`
  (plus `.sandbox-pre.sh` / `.sandbox-post.sh` for host-side firewall), builds the image, then
  runs the container once with a no-op (`true`) command to resolve the init script and leave a
  stopped container behind; **`run`** (the default) just executes `.sandbox-run.sh`.
- The Docker image is built by `project init` / `project build` (cached layers). Use
  `--no-cache` for a full rebuild.

## Python script rules

- **Stdlib only.** No pip, poetry, uv, or external packages. `argparse`, `hashlib`, `os`, `pathlib`, `re`, `shlex`, `shutil`, `subprocess`, `sys`.
- Commands are dispatched via `argparse` sub-parsers: `run` (default), `project {init,build,features,clean}`, `host {network {blacklist,whitelist,clean,init-blacklist,init-whitelist}}`, `version`, `reset`.
- `main()` prepends `run` when there is no subcommand (so bare `sandbox-code`, `sandbox-code --bash` and `sandbox-code -- cmd` work); `sandbox-code -h/--help` still prints top-level help.
- `run` and `project build` use `argparse.REMAINDER`; `_strip_remainder()` removes the leading `--` and treats `["."]` as no-command (runs the default `opencode .`).
- All container/feature configuration is baked into `.sandbox-run.sh` at build time; `run` is deliberately dumb — it just executes the script, optionally passing an override command (`--bash` → `exec bash`, `-- cmd` → `cmd`).
- The container command itself is generated to read `.sandbox-cmd` (written by `.sandbox-run.sh` before start) so a reused container honours the current override; the file, not the container, is the source of truth for the run-time command.
- `project init` and `project build` call `_ensure_gitignore()`, which idempotently appends the generated `.sandbox-*.sh` filenames plus `.sandbox-cmd` to the workspace `.gitignore` (it never rewrites or reorders existing entries, and leaves `.sandbox-init.sh` alone since that is user-editable). `project clean` reverses this via `_clean_gitignore()`.
- Firewall logic has a **single source**: `_firewall_script()` emits the shell for `.sandbox-pre.sh` / `.sandbox-post.sh`. `host network blacklist|whitelist|clean` run that same generated shell via `_run_shell()` — there is no parallel Python iptables/nft code path to keep in sync.

## Docker image (`Dockerfile`)

- Base: `ubuntu:26.04`. Runs as non-root `ubuntu` user.
- Multiple apt repos merged into a single RUN step to keep layers low.
- No Docker CLI, no socket mount — the container has no host Docker access.
- Persistent dirs (`~/.config/opencode`, `~/.local/share/opencode`) are pre-created and chowned to `ubuntu` so bind mounts inherit correct ownership.
- **No language runtimes or optional tooling are baked in** beyond the essentials (git, curl, wget, vim, jq, build-essential, ca-certificates, `python3`, Node.js — the last required by `@opencode/cli`). Go, Java/Maven, Clojure, Chromium, and the former utilities (`poppler-utils`, `gping bind9-dnsutils iproute2 iputils-ping`, `xclip xsel`, `rlwrap`) are installed per project via an **opt-in** `.sandbox-init.sh` placed in the workspace root (see the `project build` command's `--init-script` / `--force-init` / `--no-init` flags). The repo ships a `.sandbox-init.sh` **template** under `templates/` for this; projects without one get nothing extra. Chromium is **not** shipped: Ubuntu's `chromium-browser` apt package is a snap stub that cannot run inside the container — projects needing a headless browser install their own copy (e.g. `npx playwright install --with-deps chromium`).

## Volumes & mounts

- Host workspace → `/workspace` (via `-w`, default `.`)
- `~/.config/sandbox-code/opencode-config` → `/home/ubuntu/.config/opencode`
- `~/.config/sandbox-code/opencode-data` → `/home/ubuntu/.local/share/opencode`
- `--ssh`: mounts host `~/.ssh` → container read-only. **Security caveat: exposes SSH private keys to the agent** (read-only still allows reading/exfiltration). Mount only when needed.
- `--github`: mounts `~/.ssh` (ro) + `~/.config/gh` (rw). **Security caveat: exposes SSH keys and the GitHub token (rw) to the agent.** Not used by the current maintainer; kept from the original author.
- `--x11`: mounts the X11 socket + `XAUTHORITY` (ro). **Security caveat: gives the container access to the host display (keylogging, screen capture, input injection), not just the clipboard.** Effectively unnecessary for copy/paste: OpenCode emits OSC 52 on every copy, and Shift+selection works in VTE terminals (e.g. lxterminal). Kept for users who rely on `xclip`/`xsel` inside the container.
- `--no-git`: `_ensure_project_git()` creates a disposable per-workspace git repo under `~/.config/sandbox-code/gitmirror/<sha256(workspace)[:16]/.git` (init + one empty commit) and mounts it over `/workspace/.git`, hiding the real repo while giving OpenCode a stable `project_id`. Falls back to a tmpfs if `git` is unavailable on the host.
- `--openspec`: bakes an `_openspec_prefix()` snippet into the container command that (once per project, marker-guarded) runs `sudo npm install -g @fission-ai/openspec@latest` and `openspec init --tools opencode` in `/workspace`. `config/opencode.jsonc` enables the `opencode-2-openspec-plugin` (V2 `plugins` key) and maps its `openspec-planner` primary agent to `openrouter/deepseek/deepseek-v4-pro`. Needs network, so it conflicts with `--no-network`.
- Mounts are written into `.sandbox-run.sh` as literal `docker run` arguments; there is no host-side dedup helper anymore.

## Env vars

- `HOME` forced to `/home/ubuntu` in the container.
- API keys forwarded only if set in host env (not cleared if absent).
- Supported: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, `ZAI_API_KEY`, `OPENROUTER_API_KEY`, `GOOGLE_API_KEY`, `OPENCODE_API_KEY`.

## Gotchas

- The container **persists** between launches (created without `--rm`): its name is deterministic — `sandbox-code-<workspace-folder-name>`. Later launches `docker start -ai` the same container, keeping init-installed packages. Run `sandbox-code project clean` (or `docker rm -f sandbox-code-<folder>`) to force a fresh container.
- On resume, the container re-runs its baked command, which reads `.sandbox-cmd` from the mounted workspace — so a run-time command override (`run --bash`, `run -- cmd`) works even on an existing container. Mount/feature flags (`--ssh`, `--x11`, …) are baked by `project build`; to change them, re-run `project build` and `project clean`.
- `-it` is chosen at run time inside `.sandbox-run.sh` (`[[ -t 0 ]]`) — batch runs use `-i` only.
- Container hostname is `sandbox-code`; the container *name* is `sandbox-code-<folder-name>`.