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

- **Stdlib only.** No pip, poetry, uv, or external packages. `argparse`, `os`, `pathlib`, `shutil`, `subprocess`, `sys`.
- `argparse.REMAINDER` captures `--` itself — line 85 strips it explicitly.
- `["."]` as the only command is treated as no-command (line 87). Runs default `opencode .` instead.

## Docker image (`Dockerfile`)

- Base: `ubuntu:26.04`. Runs as non-root `sandbox` user.
- Multiple apt repos merged into a single RUN step to keep layers low.
- No Docker CLI, no socket mount — the container has no host Docker access.
- Persistent dirs (`~/.config/opencode`, `~/.local/share/opencode`) are pre-created and chowned to `sandbox` so bind mounts inherit correct ownership.

## Volumes & mounts

- Host workspace → `/workspace` (via `-w`, default `.`)
- `~/.config/sandbox-code/opencode-config` → `/home/sandbox/.config/opencode`
- `~/.config/sandbox-code/opencode-data` → `/home/sandbox/.local/share/opencode`
- `--ssh`: mounts host `~/.ssh` → container read-only
- `--github`: mounts `~/.ssh` (ro) + `~/.config/gh` (rw)
- `add_mount()` deduplicates by destination — same mount target never added twice.

## Env vars

- `HOME` forced to `/home/sandbox` in the container.
- API keys forwarded only if set in host env (not cleared if absent).
- Supported: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, `ZAI_API_KEY`, `OPENROUTER_API_KEY`, `GOOGLE_API_KEY`, `OPENCODE_API_KEY`.

## Gotchas

- `docker rm -f sandbox-code` runs silently before every launch to prevent stale container name conflicts.
- `-it` only added when `sys.stdin.isatty()` — batch runs use `-i` only.
- Container hostname == container name == `sandbox-code`.