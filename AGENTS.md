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
- **Headless Chromium** (`chromium-browser`) is installed. Use `chromium-browser --headless` or `chromium-browser --headless=new` for headless mode. For Playwright/Puppeteer, set `PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium-browser`.

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

- `docker rm -f sandbox-code` runs silently before every launch to prevent stale container name conflicts.
- `-it` only added when `sys.stdin.isatty()` — batch runs use `-i` only.
- Container hostname == container name == `sandbox-code`.