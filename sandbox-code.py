#!/usr/bin/env python3
import argparse
import os
import pathlib
import shutil
import subprocess
import sys

SANDBOX_HOME = pathlib.Path.home() / ".config" / "sandbox-code"
CONFIG_DIR = SANDBOX_HOME / "opencode-config"
DATA_DIR = SANDBOX_HOME / "opencode-data"
SSH_DIR = pathlib.Path.home() / ".ssh"
GH_DIR = pathlib.Path.home() / ".config" / "gh"

API_KEY_VARS = [
    "DEEPSEEK_API_KEY",
    "ZAI_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "OPENCODE_API_KEY",
]


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))

    parser = argparse.ArgumentParser(
        description="Start sandbox-code Docker container with OpenCode"
    )
    parser.add_argument(
        "-w", "--workspace",
        default=os.getcwd(),
        help="Directory to mount as /workspace (default: current directory)",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print OpenCode version and exit",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete all persistent data before starting",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Force a full rebuild without Docker layer cache",
    )
    parser.add_argument(
        "--bash",
        action="store_true",
        help="Start with an interactive bash shell instead of opencode",
    )
    parser.add_argument(
        "--ssh",
        action="store_true",
        help="Mount ~/.ssh into the container (read-only)",
    )
    parser.add_argument(
        "--github",
        action="store_true",
        help="Mount ~/.ssh (read-only) and ~/.config/gh (writable)",
    )
    parser.add_argument(
        "--x11",
        action="store_true",
        help="Mount X11 socket for clipboard support (enables copy/paste)",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Command to run inside the container (default: opencode .)",
    )

    args = parser.parse_args()

    if args.version:
        subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "opencode",
             "sandbox-code:latest", "--version"],
            env=os.environ,
            check=True,
        )
        return

    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if command == ["."]:
        command = []

    if args.reset:
        shutil.rmtree(CONFIG_DIR, ignore_errors=True)
        shutil.rmtree(DATA_DIR, ignore_errors=True)

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    _project_root = pathlib.Path(script_dir)
    for name in ("opencode.jsonc", "tui.json"):
        dst = CONFIG_DIR / name
        if not dst.exists():
            src = _project_root / name
            if src.exists():
                shutil.copy2(src, dst)

    build_cmd = ["docker", "build", "-t", "sandbox-code:latest"]
    if args.no_cache:
        build_cmd.append("--no-cache")
    build_cmd.append(script_dir)

    subprocess.run(build_cmd, env=os.environ, check=True)

    workspace = os.path.abspath(args.workspace)

    run_mode = ["-it"] if sys.stdin.isatty() else ["-i"]

    docker_cmd = [
        "docker", "run", "--rm",
        *run_mode,
        "--hostname", "sandbox-code",
        "--name", "sandbox-code",
        "-v", f"{workspace}:/workspace",
        "-v", f"{CONFIG_DIR}:/home/ubuntu/.config/opencode",
        "-v", f"{DATA_DIR}:/home/ubuntu/.local/share/opencode",
        "-e", "HOME=/home/ubuntu",
        "-e", f'TERM={os.environ.get("TERM", "xterm-256color")}',
        "-e", f'LANG={os.environ.get("LANG", "C.UTF-8")}',
        "-e", f'LC_ALL={os.environ.get("LC_ALL", "C.UTF-8")}',
        "-w", "/workspace",
    ]

    # X11 support for clipboard
    if args.x11:
        # Pass DISPLAY environment variable
        if "DISPLAY" in os.environ:
            docker_cmd.extend(["-e", f'DISPLAY={os.environ["DISPLAY"]}'])
            docker_cmd.extend(["-v", "/tmp/.X11-unix:/tmp/.X11-unix"])
            print("[INFO] X11 support enabled (DISPLAY={})".format(os.environ["DISPLAY"]))
        else:
            print("[WARNING] --x11 requested but DISPLAY not set in environment", file=sys.stderr)
        
        # Also try to detect and pass XAUTHORITY if available
        if "XAUTHORITY" in os.environ:
            docker_cmd.extend(["-e", f'XAUTHORITY={os.environ["XAUTHORITY"]}'])
            docker_cmd.extend(["-v", f'{os.environ["XAUTHORITY"]}:{os.environ["XAUTHORITY"]}'])
        
        # Additional common Xauthority location
        xauth_path = pathlib.Path.home() / ".Xauthority"
        if xauth_path.exists():
            docker_cmd.extend(["-v", f"{xauth_path}:/home/ubuntu/.Xauthority:ro"])
            docker_cmd.extend(["-e", "XAUTHORITY=/home/ubuntu/.Xauthority"])

        # Wayland support (if using Wayland with XWayland)
        if "WAYLAND_DISPLAY" in os.environ:
            runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "/run/user/1000")
            wayland_display = os.environ["WAYLAND_DISPLAY"]
            docker_cmd.extend(["-e", f'WAYLAND_DISPLAY={wayland_display}'])
            docker_cmd.extend(["-v", f"{runtime_dir}/{wayland_display}:/tmp/{wayland_display}"])
            docker_cmd.extend(["-e", "XDG_RUNTIME_DIR=/tmp"])
            print("[INFO] Wayland socket mounted for XWayland support")

    mounts = set()

    def add_mount(src, dst, readonly=True):
        if dst not in mounts:
            if readonly:
                docker_cmd.extend(["-v", f"{src}:{dst}:ro"])
            else:
                docker_cmd.extend(["-v", f"{src}:{dst}"])
            mounts.add(dst)

    if args.github:
        if GH_DIR.is_dir():
            add_mount(GH_DIR, "/home/ubuntu/.config/gh", readonly=False)
        if SSH_DIR.is_dir():
            add_mount(SSH_DIR, "/home/ubuntu/.ssh")

    if args.ssh and not args.github:
        if SSH_DIR.is_dir():
            add_mount(SSH_DIR, "/home/ubuntu/.ssh")

    for var in API_KEY_VARS:
        if var in os.environ:
            docker_cmd.extend(["-e", var])

    docker_cmd.append("sandbox-code:latest")

    if command:
        docker_cmd.extend(["-c", " ".join(command)])
    elif args.bash:
        pass
    else:
        docker_cmd.extend(["-c", "opencode ."])

    subprocess.run(["docker", "rm", "-f", "sandbox-code"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        subprocess.run(docker_cmd, env=os.environ, check=True)
    except subprocess.CalledProcessError as e:
        sys.exit(e.returncode)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
