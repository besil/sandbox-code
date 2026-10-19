# AGENTS.md

## Repo overview

Dockerised OpenCode sandbox. No build/test/lint pipeline — this is an infrastructure project.

## Architecture

```
sandbox-code (shell wrapper) → sandbox-code.py (Python) → docker run sandbox-code:latest
```

- `sandbox-code` is a bash `exec` wrapper that finds `sandbox-code.py` relative to itself, then delegates.
- `sandbox-code.py` builds the Docker image from `Dockerfile`, then runs it with `docker run`.
- The Docker image is always rebuilt on every launch (cached layers). Use `--no-cache` for a full rebuild.

## Python script rules

- **Stdlib only.** No pip, poetry, uv, or external packages. `argparse`, `hashlib`, `os`, `pathlib`, `shutil`, `subprocess`, `sys`.
- `argparse.REMAINDER` captures `--` itself — line 140 strips it explicitly.
- `["."]` as the only command is treated as no-command (line 142). Runs default `opencode .` instead.

## Docker image (`Dockerfile`)

- Base: `ubuntu:26.04`. Runs as non-root `ubuntu` user.
- Multiple apt repos merged into a single RUN step to keep layers low.
- No Docker CLI, no socket mount — the container has no host Docker access.
- Persistent dirs (`~/.config/opencode`, `~/.local/share/opencode`) are pre-created and chowned to `ubuntu` so bind mounts inherit correct ownership.
- **No language runtimes or optional tooling are baked in** beyond the essentials (git, curl, wget, vim, jq, build-essential, ca-certificates, `python3`, Node.js — the last required by `opencode-ai`). Go, Java/Maven, Clojure, Chromium, and the former utilities (`poppler-utils`, `gping bind9-dnsutils iproute2 iputils-ping`, `xclip xsel`, `rlwrap`) are installed per project via an **opt-in** `.sandbox-init.sh` placed in the workspace root (see `sandbox-code.py`'s `--init-script` / `--force-init` / `--no-init` flags). The repo ships a `.sandbox-init.sh` **template** for this; projects without one get nothing extra. Chromium is **not** shipped: Ubuntu's `chromium-browser` apt package is a snap stub that cannot run inside the container — projects needing a headless browser install their own copy (e.g. `npx playwright install --with-deps chromium`).

## Volumes & mounts

- Host workspace → `/workspace` (via `-w`, default `.`)
- `~/.config/sandbox-code/opencode-config` → `/home/ubuntu/.config/opencode`
- `~/.config/sandbox-code/opencode-data` → `/home/ubuntu/.local/share/opencode`
- `--ssh`: mounts host `~/.ssh` → container read-only. **Security caveat: exposes SSH private keys to the agent** (read-only still allows reading/exfiltration). Mount only when needed.
- `--github`: mounts `~/.ssh` (ro) + `~/.config/gh` (rw). **Security caveat: exposes SSH keys and the GitHub token (rw) to the agent.** Not used by the current maintainer; kept from the original author.
- `--x11`: mounts the X11 socket + `XAUTHORITY` (ro). **Security caveat: gives the container access to the host display (keylogging, screen capture, input injection), not just the clipboard.** Effectively unnecessary for copy/paste: OpenCode emits OSC 52 on every copy, and Shift+selection works in VTE terminals (e.g. lxterminal). Kept for users who rely on `xclip`/`xsel` inside the container.
- `--no-git`: `_ensure_project_git()` creates a disposable per-workspace git repo under `~/.config/sandbox-code/gitmirror/<sha256(workspace)[:16]/.git` (init + one empty commit) and mounts it over `/workspace/.git`, hiding the real repo while giving OpenCode a stable `project_id`. Falls back to a tmpfs if `git` is unavailable on the host.
- `add_mount()` deduplicates by destination — same mount target never added twice.

## Env vars

- `HOME` forced to `/home/ubuntu` in the container.
- API keys forwarded only if set in host env (not cleared if absent).
- Supported: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, `ZAI_API_KEY`, `OPENROUTER_API_KEY`, `GOOGLE_API_KEY`, `OPENCODE_API_KEY`.

## Gotchas

- The container **persists** between launches (created without `--rm`): its name is deterministic — `sandbox-code-<workspace-folder-name>`. Later launches `docker start -ai` the same container, keeping init-installed packages. Run `sandbox-code --clean-project` (or `docker rm -f sandbox-code-<folder>`) to force a fresh container.
- On resume, the container re-runs its **original** baked command — flags passed on later launches (e.g. `--ssh`, `--bash`) only apply at first creation.
- `-it` only added when `sys.stdin.isatty()` — batch runs use `-i` only.
- Container hostname is `sandbox-code`; the container *name* is `sandbox-code-<folder-name>`.