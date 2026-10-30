#!/usr/bin/env python3
import argparse
import hashlib
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys

SANDBOX_HOME = pathlib.Path.home() / ".config" / "sandbox-code"
CONFIG_DIR = SANDBOX_HOME / "opencode-config"
DATA_DIR = SANDBOX_HOME / "opencode-data"
GITMIRROR_DIR = SANDBOX_HOME / "gitmirror"
SSH_DIR = pathlib.Path.home() / ".ssh"
GH_DIR = pathlib.Path.home() / ".config" / "gh"

# Repo asset locations (paths relative to the repo root, i.e. script_dir).
TEMPLATES_SUBDIR = "templates"
CONFIG_SUBDIR = "config"
FIREWALL_SUBDIR = os.path.join("config", "firewall")

# Generated project files live in a hidden folder inside the workspace.
SANDBOX_DIR = ".sandbox-code"
RUN_SCRIPT_NAME = "sandbox-run.sh"
PRE_SCRIPT_NAME = "sandbox-pre.sh"
POST_SCRIPT_NAME = "sandbox-post.sh"
INIT_SCRIPT_NAME = "sandbox-init.sh"
# Holds the command the container should run; read at container start so an
# existing (persistent) container can be reused with a different command.
CMD_FILE_NAME = "sandbox-cmd"

# Default init script, relative to the workspace root.
DEFAULT_INIT_SCRIPT = os.path.join(SANDBOX_DIR, INIT_SCRIPT_NAME)


def _sb_dir(workspace):
    """Host path to the workspace's .sandbox-code directory."""
    return os.path.join(workspace, SANDBOX_DIR)


def _sb_file(workspace, name):
    """Host path to a file inside the workspace's .sandbox-code directory."""
    return os.path.join(workspace, SANDBOX_DIR, name)


def _sb_container(name):
    """Container-side path for a file in .sandbox-code (mounted at /workspace)."""
    return f"/workspace/{SANDBOX_DIR}/{name}"


API_KEY_VARS = [
    "DEEPSEEK_API_KEY",
    "ZAI_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "OPENCODE_API_KEY",
]


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    parser = _build_parser()

    # With no subcommand, behave like `run` (so `sandbox-code`,
    # `sandbox-code --bash` and `sandbox-code -- cmd` all work).
    argv = sys.argv[1:]
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help")):
        argv = ["run", *argv]
    args = parser.parse_args(argv)

    sub = args.subcommand

    if sub == "run" or sub is None:
        cmd_run(script_dir, args)
    elif sub == "version":
        cmd_version()
    elif sub == "reset":
        cmd_reset()
    elif sub == "project":
        _dispatch_project(script_dir, parser, args)
    elif sub == "host":
        _dispatch_host(script_dir, parser, args)
    else:  # pragma: no cover - argparse guards this
        parser.error(f"unknown command: {sub}")


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="sandbox-code",
        description="Run OpenCode inside a Dockerised sandbox.",
        epilog=(
            "Commands: run (default), project, host, version, reset. "
            "Run 'sandbox-code <command> --help' for details."
        ),
    )
    sub = parser.add_subparsers(dest="subcommand", metavar="<command>")

    # -- run -----------------------------------------------------------------
    p = sub.add_parser("run", help="Execute the generated .sandbox-code/sandbox-run.sh")
    _add_run_args(p)

    # -- project -------------------------------------------------------------
    p = sub.add_parser("project", help="Manage the current project")
    psub = p.add_subparsers(dest="project_command", metavar="<subcommand>")

    sp = psub.add_parser("init", help="Create .sandbox-code/sandbox-init.sh and .sandbox-code/sandbox-run.sh")
    _add_workspace_arg(sp)

    sp = psub.add_parser(
        "build",
        help="Generate/update .sandbox-code/sandbox-run.sh and build the Docker image",
    )
    _add_workspace_arg(sp)
    _add_build_args(sp)

    sp = psub.add_parser("features", help="List the features enabled for this project")
    _add_workspace_arg(sp)

    sp = psub.add_parser(
        "clean", help="Remove the container, init marker and generated files",
    )
    _add_workspace_arg(sp)

    # -- host ----------------------------------------------------------------
    p = sub.add_parser("host", help="Manage host-side settings")
    hsub = p.add_subparsers(dest="host_command", metavar="<subcommand>")

    p = hsub.add_parser("network", help="Manage network isolation")
    nsub = p.add_subparsers(dest="network_command", metavar="<subcommand>")

    for name, help_text in (
        ("blacklist", "Apply blacklist firewall rules on the host"),
        ("whitelist", "Apply whitelist firewall rules on the host"),
        ("clean", "Remove all firewall rules created by sandbox-code"),
        ("init-blacklist", "Create a default blacklist-networks.conf in the workspace"),
        ("init-whitelist", "Create a default whitelist-networks.conf in the workspace"),
    ):
        sp = nsub.add_parser(name, help=help_text)
        _add_workspace_arg(sp)

    # -- top-level -----------------------------------------------------------
    sub.add_parser("version", help="Print the OpenCode version and exit")
    sub.add_parser("reset", help="Delete all persistent data (config, data, gitmirror)")

    return parser


def _add_workspace_arg(parser):
    parser.add_argument(
        "-w", "--workspace", default=os.getcwd(),
        help="Directory to mount as /workspace (default: current directory)",
    )


def _add_run_args(parser):
    _add_workspace_arg(parser)
    parser.add_argument(
        "--bash", action="store_true",
        help="Drop into an interactive bash shell instead of the configured command",
    )
    parser.add_argument(
        "--new-session", action="store_true",
        help="Start a new OpenCode session instead of continuing the previous one",
    )
    parser.add_argument(
        "command", nargs=argparse.REMAINDER,
        help="Override the command to run inside the container "
             "(default: the command baked into .sandbox-code/sandbox-run.sh)",
    )


def _add_build_args(parser):
    parser.add_argument(
        "--no-cache", action="store_true",
        help="Force a full Docker image rebuild without layer cache",
    )
    parser.add_argument(
        "--ssh", action="store_true",
        help="Mount ~/.ssh into the container (read-only). SECURITY: exposes your "
             "SSH private keys to the agent for the whole session",
    )
    parser.add_argument(
        "--github", action="store_true",
        help="Mount ~/.ssh (read-only) and ~/.config/gh (writable). SECURITY: "
             "exposes your SSH keys and GitHub token (rw) to the agent",
    )
    parser.add_argument(
        "--x11", action="store_true",
        help="Mount X11 socket for clipboard support (enables copy/paste)",
    )
    parser.add_argument(
        "--no-git", action="store_true",
        help="Hide the real .git, exposing a disposable per-project repo instead",
    )
    parser.add_argument(
        "--openspec", action="store_true",
        help="Install the OpenSpec CLI and initialize its OpenCode integration "
             "(runs once on first container start)",
    )
    parser.add_argument(
        "--no-init", action="store_true",
        help="Skip the project init script entirely",
    )
    parser.add_argument(
        "--init-script", default=DEFAULT_INIT_SCRIPT,
        help=f"Init script to run inside the container, relative to workspace "
             f"(default: {DEFAULT_INIT_SCRIPT})",
    )
    parser.add_argument(
        "--force-init", action="store_true",
        help="Drop the per-project marker so the init script runs again",
    )
    parser.add_argument(
        "--no-network", action="store_true",
        help="Disable all networking (--network none)",
    )
    parser.add_argument(
        "--network", type=str, default=None,
        help="Docker network to use (default: bridge)",
    )
    parser.add_argument(
        "--blacklist", action="store_true",
        help="Isolate from local/Tailscale subnets, allow internet "
             "(blacklist-networks.conf)",
    )
    parser.add_argument(
        "--whitelist", action="store_true",
        help="Allow only listed CIDRs, block everything else "
             "(whitelist-networks.conf)",
    )
    parser.add_argument(
        "command", nargs=argparse.REMAINDER,
        help="Command to run inside the container (default: opencode .)",
    )


def _dispatch_project(script_dir, parser, args):
    pc = getattr(args, "project_command", None)
    if pc == "init":
        cmd_project_init(script_dir, args)
    elif pc == "build":
        cmd_project_build(script_dir, args)
    elif pc == "features":
        cmd_project_features(args)
    elif pc == "clean":
        cmd_project_clean(script_dir, args)
    else:
        parser.error("project requires a subcommand: init, build, features, clean")


def _dispatch_host(script_dir, parser, args):
    hc = getattr(args, "host_command", None)
    if hc == "network":
        _dispatch_network(script_dir, parser, args)
    else:
        parser.error("host requires a subcommand: network")


def _dispatch_network(script_dir, parser, args):
    nc = getattr(args, "network_command", None)
    if nc in ("blacklist", "whitelist"):
        cmd_network_apply(script_dir, args, nc)
    elif nc == "clean":
        cmd_network_clean(script_dir, args)
    elif nc in ("init-blacklist", "init-whitelist"):
        cmd_network_init(script_dir, args, nc.replace("init-", ""))
    else:
        parser.error(
            "network requires a subcommand: blacklist, whitelist, clean, "
            "init-blacklist, init-whitelist"
        )


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_run(script_dir, args):
    workspace = os.path.abspath(getattr(args, "workspace", os.getcwd()))
    run_script = _sb_file(workspace, RUN_SCRIPT_NAME)

    if not os.path.isfile(run_script):
        print(
            f"[ERROR] No {SANDBOX_DIR}/{RUN_SCRIPT_NAME} in {workspace}",
            file=sys.stderr,
        )
        print(
            "        Run 'sandbox-code project init' or 'sandbox-code project build' first.",
            file=sys.stderr,
        )
        sys.exit(1)

    override = _strip_remainder(getattr(args, "command", []))
    if override:
        override = [" ".join(override)]
    elif getattr(args, "bash", False):
        override = ["exec bash"]
    elif getattr(args, "new_session", False):
        override = ["opencode ."]
    else:
        override = ["opencode -c"]

    _run_script(workspace, run_script, override)


def cmd_project_build(script_dir, args):
    """Generate/update .sandbox-code/sandbox-run.sh and build the Docker image."""
    workspace = os.path.abspath(args.workspace)
    network_arg, filter_mode = _resolve_network(args)
    command = _strip_remainder(args.command)

    _build_image(script_dir, args.no_cache)
    _write_project_files(
        script_dir, workspace,
        ssh=args.ssh,
        github=args.github,
        x11=args.x11,
        no_git=args.no_git,
        openspec=args.openspec,
        no_init=args.no_init,
        init_script=args.init_script,
        force_init=args.force_init,
        network_arg=network_arg,
        filter_mode=filter_mode,
        command=command,
    )

    # Resolve the init script now by running the container once with a no-op
    # command. This installs everything up front so the first real `run` is
    # instant. The container is left stopped and then reused by `run`.
    print("[INFO] Preparing container (running the init script)…")
    _run_script(workspace, _sb_file(workspace, RUN_SCRIPT_NAME), ["true"])


def cmd_project_init(script_dir, args):
    workspace = os.path.abspath(args.workspace)

    template = os.path.join(script_dir, TEMPLATES_SUBDIR, INIT_SCRIPT_NAME)
    dst = _sb_file(workspace, INIT_SCRIPT_NAME)
    if os.path.exists(dst):
        print(f"[INFO] {SANDBOX_DIR}/{INIT_SCRIPT_NAME} already exists, keeping it")
    elif os.path.exists(template):
        os.makedirs(_sb_dir(workspace), exist_ok=True)
        shutil.copy2(template, dst)
        os.chmod(dst, 0o755)
        print(f"[INFO] Created {SANDBOX_DIR}/{INIT_SCRIPT_NAME} from template")
    else:
        print(f"[WARNING] {INIT_SCRIPT_NAME} template not found in "
              f"{os.path.join(script_dir, TEMPLATES_SUBDIR)}",
              file=sys.stderr)

    _build_image(script_dir, no_cache=False)
    _write_project_files(script_dir, workspace)


def cmd_project_features(args):
    workspace = os.path.abspath(args.workspace)
    run_script = _sb_file(workspace, RUN_SCRIPT_NAME)

    if not os.path.isfile(run_script):
        print(f"[ERROR] No {SANDBOX_DIR}/{RUN_SCRIPT_NAME} in {workspace}", file=sys.stderr)
        print("        Run 'sandbox-code project init' first.", file=sys.stderr)
        sys.exit(1)

    meta = _read_metadata(run_script)
    features = set(meta.get("features", "").split())
    network = meta.get("network", "bridge")
    network_name = meta.get("network-name")
    x11 = meta.get("x11", "false") == "true"
    no_git = meta.get("no-git", "false") == "true"
    init_script = meta.get("init-script", "none")
    entry = meta.get("entrypoint", "opencode .")
    container = meta.get("container", "?")

    pre = os.path.isfile(_sb_file(workspace, PRE_SCRIPT_NAME))
    post = os.path.isfile(_sb_file(workspace, POST_SCRIPT_NAME))

    def line(label, state, detail=""):
        state_col = f"{state:<9}"
        print(f"  {label:<14} {state_col} {detail}".rstrip())

    print(f"Features for {workspace}")
    print(f"  Container:     {container}")
    print()

    if "ssh" in features:
        line("SSH", "enabled", "~/.ssh mounted read-only")
    else:
        line("SSH", "disabled")

    if "github" in features:
        line("GitHub", "enabled", "~/.ssh + ~/.config/gh mounted")
    else:
        line("GitHub", "disabled")

    line("X11", "enabled" if x11 else "disabled")
    line("No-git", "enabled" if no_git else "disabled")
    line("OpenSpec", "enabled" if "openspec" in features else "disabled")

    if init_script != "none":
        line("Init script", "enabled", init_script)
    else:
        line("Init script", "disabled")

    if network in ("blacklist", "whitelist"):
        detail = network_name or ""
        line("Network", network, f"({detail})" if detail else "")
    else:
        line("Network", network)

    print(f"  Entry point:   {entry}")
    print()
    line("Pre-hook", "present" if pre else "absent", f"{SANDBOX_DIR}/{PRE_SCRIPT_NAME}")
    line("Post-hook", "present" if post else "absent", f"{SANDBOX_DIR}/{POST_SCRIPT_NAME}")
    print()
    print("Change any of these with: sandbox-code project build [options]")


def cmd_project_clean(script_dir, args):
    workspace = os.path.abspath(args.workspace)

    ctr_name = _container_name(workspace)
    subprocess.run(
        ["docker", "rm", "-f", ctr_name],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    print(f"[INFO] Removed container '{ctr_name}' (if it existed)")

    # Determine which init script was in use (for the marker key).
    init_script = DEFAULT_INIT_SCRIPT
    run_script = _sb_file(workspace, RUN_SCRIPT_NAME)
    if os.path.isfile(run_script):
        meta = _read_metadata(run_script)
        if meta.get("init-script") and meta["init-script"] != "none":
            init_script = meta["init-script"]

    workspace_key = hashlib.sha256(
        (workspace + ":" + init_script).encode()).hexdigest()[:16]
    marker_file = DATA_DIR / ".init-done" / workspace_key
    marker_file.unlink(missing_ok=True)

    openspec_key = hashlib.sha256(
        (workspace + ":openspec").encode()).hexdigest()[:16]
    (DATA_DIR / ".init-done" / openspec_key).unlink(missing_ok=True)

    for name in (RUN_SCRIPT_NAME, PRE_SCRIPT_NAME, POST_SCRIPT_NAME, CMD_FILE_NAME):
        path = _sb_file(workspace, name)
        if os.path.exists(path):
            os.remove(path)
            print(f"[INFO] Removed {SANDBOX_DIR}/{name}")

    _clean_gitignore(workspace)


def cmd_network_apply(script_dir, args, mode):
    workspace = os.path.abspath(args.workspace)
    conf_path = _find_conf(workspace, script_dir, mode)
    network, iface, cidrs = _ensure_network(conf_path)
    _run_shell(_firewall_script(mode, "pre", network, iface, cidrs))
    print(f"[INFO] {mode} rules applied on network '{network}' (iface {iface})")


def cmd_network_clean(script_dir, args):
    workspace = os.path.abspath(args.workspace)
    cleaned = False

    for mode in ("blacklist", "whitelist"):
        conf_path = _find_conf(workspace, script_dir, mode)
        if not os.path.isfile(conf_path):
            continue
        network, _subnet, cidrs = _load_filter_config(conf_path)
        try:
            iface = _bridge_iface(network)
        except subprocess.CalledProcessError:
            print(f"[INFO] Network '{network}' not found, skipping {mode} cleanup")
            continue
        _run_shell(_firewall_script(mode, "post", network, iface, cidrs))
        cleaned = True

    # Remove the nft table wholesale (covers cases with no config file present).
    if _nft_available():
        subprocess.run(["sudo", "nft", "delete", "table", _NFT_TABLE],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cleaned = True

    if cleaned:
        print("[INFO] Firewall rules removed")
    else:
        print("[WARNING] No firewall tool (iptables/nft) available, nothing cleaned",
              file=sys.stderr)


def cmd_network_init(script_dir, args, mode):
    workspace = os.path.abspath(args.workspace)
    name = f"{mode}-networks.conf"
    dst = os.path.join(workspace, name)
    if os.path.exists(dst):
        print(f"[INFO] {name} already exists, keeping it")
        return

    template = os.path.join(script_dir, FIREWALL_SUBDIR, name)
    if not os.path.isfile(template):
        print(f"[ERROR] Template not found: {template}", file=sys.stderr)
        sys.exit(1)
    shutil.copy2(template, dst)
    print(f"[INFO] Created {name}")


def cmd_version():
    subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "opencode",
         "sandbox-code:latest", "--version"],
        env=os.environ,
        check=True,
    )


def cmd_reset():
    shutil.rmtree(CONFIG_DIR, ignore_errors=True)
    shutil.rmtree(DATA_DIR, ignore_errors=True)
    shutil.rmtree(GITMIRROR_DIR, ignore_errors=True)
    print("[INFO] Removed persistent data")


# ---------------------------------------------------------------------------
# build-phase helpers
# ---------------------------------------------------------------------------

def _strip_remainder(command):
    command = list(command or [])
    if command and command[0] == "--":
        command = command[1:]
    if command == ["."]:
        command = []
    return command


def _resolve_network(args):
    """Return (network_name_or_none, filter_mode_or_none) from build args."""
    flags = [args.no_network, bool(args.network), args.blacklist, args.whitelist]
    if sum(flags) > 1:
        pieces = []
        if args.no_network:
            pieces.append("--no-network")
        if args.network:
            pieces.append("--network")
        if args.blacklist:
            pieces.append("--blacklist")
        if args.whitelist:
            pieces.append("--whitelist")
        print(f"[ERROR] {', '.join(pieces)} are mutually exclusive", file=sys.stderr)
        sys.exit(2)

    if args.blacklist:
        return None, "blacklist"
    if args.whitelist:
        return None, "whitelist"
    if args.no_network:
        return "none", None
    if args.network:
        return args.network, None
    return None, None


def _build_image(script_dir, no_cache=False):
    cmd = ["docker", "build", "-t", "sandbox-code:latest"]
    if no_cache:
        cmd.append("--no-cache")
    cmd.append(script_dir)
    subprocess.run(cmd, env=os.environ, check=True)


def _init_prefix(workspace, init_script):
    """Shell snippet (run inside the container) that runs the init script once."""
    workspace_key = hashlib.sha256(
        (workspace + ":" + init_script).encode()).hexdigest()[:16]
    script_path = f"/workspace/{init_script}"
    marker_path = f"/home/ubuntu/.local/share/opencode/.init-done/{workspace_key}"
    return (
        f'mkdir -p "$(dirname {marker_path})" && '
        f'SCRIPT="{script_path}" && '
        f'MARKER="{marker_path}" && '
        f'[ -f "$SCRIPT" ] && '
        f'if [ ! -f "$MARKER" ] || '
        f'[ "$(sha256sum "$SCRIPT" | awk \'{{print $1}}\')" != "$(cat "$MARKER")" ]; then '
        f'sudo bash "$SCRIPT" && '
        f'sha256sum "$SCRIPT" | awk \'{{print $1}}\' > "$MARKER"; '
        f'fi; '
    )


def _openspec_prefix(workspace):
    """Shell snippet (run inside the container) that sets up OpenSpec once."""
    workspace_key = hashlib.sha256(
        (workspace + ":openspec").encode()).hexdigest()[:16]
    marker_path = f"/home/ubuntu/.local/share/opencode/.init-done/{workspace_key}"
    return (
        f'mkdir -p "$(dirname {marker_path})" && '
        f'MARKER="{marker_path}" && '
        f'if [ ! -f "$MARKER" ]; then '
        f'sudo npm install -g @fission-ai/openspec@latest && '
        f'openspec init --tools opencode && '
        f'touch "$MARKER"; '
        f'fi; '
    )


def _write_project_files(script_dir, workspace, *, ssh=False, github=False,
                         x11=False, no_git=False, openspec=False, no_init=False,
                         init_script=DEFAULT_INIT_SCRIPT, force_init=False,
                         network_arg=None, filter_mode=None, command=None):
    """Generate .sandbox-code/sandbox-run.sh (and host pre/post hooks)."""
    workspace = os.path.abspath(workspace)
    command = command or []
    os.makedirs(_sb_dir(workspace), exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Seed persistent OpenCode config from the repo defaults (once).
    for name in ("opencode.jsonc", "cli.json"):
        dst = CONFIG_DIR / name
        if not dst.exists():
            src = pathlib.Path(script_dir) / CONFIG_SUBDIR / name
            if src.exists():
                shutil.copy2(src, dst)

    workspace_key = hashlib.sha256(
        (workspace + ":" + init_script).encode()).hexdigest()[:16]
    marker_host = DATA_DIR / ".init-done" / workspace_key

    openspec_key = hashlib.sha256(
        (workspace + ":openspec").encode()).hexdigest()[:16]
    openspec_marker_host = DATA_DIR / ".init-done" / openspec_key

    init_prefix = "" if no_init else _init_prefix(workspace, init_script)
    init_prefix = "" if no_init else _init_prefix(workspace, init_script)
    openspec_prefix = _openspec_prefix(workspace) if openspec else ""
    default_cmd = " ".join(command) if command else "opencode -c"
    container = _container_name(workspace)

    # The container's baked command reads the desired command from the mounted
    # workspace at start time, runs the init step, then eval's that command.
    # This lets the persistent container be reused with a different command
    # (e.g. `run --bash`) without being recreated.
    container_cmd = (
        f'CMD="$(cat {_sb_container(CMD_FILE_NAME)} 2>/dev/null || echo opencode .)"; '
        + init_prefix
        + openspec_prefix
        + 'eval "$CMD"'
    )

    # --- network / firewall -------------------------------------------------
    network_name = None
    dns_args = []
    if filter_mode:
        conf_path = _find_conf(workspace, script_dir, filter_mode)
        network_name, iface, cidrs = _ensure_network(conf_path)
        network_arg = network_name
        dns_args = ["--dns", "1.1.1.1", "--dns", "8.8.8.8"]
        _write_firewall_scripts(workspace, filter_mode, network_name, iface, cidrs)
    else:
        for name in (PRE_SCRIPT_NAME, POST_SCRIPT_NAME):
            stale = _sb_file(workspace, name)
            if os.path.exists(stale):
                os.remove(stale)

    features = [f for f, on in
                (("ssh", ssh), ("github", github), ("x11", x11), ("no-git", no_git),
                 ("openspec", openspec))
                if on]

    # --- compose the run script --------------------------------------------
    L = []
    L.append("#!/usr/bin/env bash")
    L.append("# @generated-by: sandbox-code")
    L.append(f"# @workspace: {workspace}")
    L.append(f"# @container: {container}")
    L.append(f"# @features: {' '.join(features) if features else 'none'}")
    L.append(f"# @network: {filter_mode or network_arg or 'bridge'}")
    if network_name:
        L.append(f"# @network-name: {network_name}")
    L.append(f"# @entrypoint: {default_cmd}")
    L.append(f"# @init-script: {'none' if no_init else init_script}")
    L.append(f"# @no-git: {str(no_git).lower()}")
    L.append(f"# @x11: {str(x11).lower()}")
    L.append(f"# @openspec: {str(openspec).lower()}")
    L.append("#")
    L.append("# Generated by 'sandbox-code project build'. Inspect, edit, or run directly:")
    L.append(f"#   bash {SANDBOX_DIR}/{RUN_SCRIPT_NAME}")
    L.append("#")
    L.append("# An optional argument overrides the command run inside the container:")
    L.append(f"#   bash {SANDBOX_DIR}/{RUN_SCRIPT_NAME} 'exec bash'")
    L.append("set -eo pipefail")
    L.append("")
    L.append(f"WORKSPACE={shlex.quote(workspace)}")
    L.append(f'SB_DIR="$WORKSPACE/{SANDBOX_DIR}"')
    L.append(f'CONTAINER={shlex.quote(container)}')
    L.append(f"CONTAINER_CMD={shlex.quote(container_cmd)}")
    L.append(f"DEFAULT_CMD={shlex.quote(default_cmd)}")
    L.append("")
    L.append("# Resolve the command for this launch: override via args, else the default")
    L.append('if [[ $# -gt 0 ]]; then')
    L.append('  CMD="$*"')
    L.append("else")
    L.append('  CMD="$DEFAULT_CMD"')
    L.append("fi")
    L.append("")
    L.append(f"# Publish it for the container to read at start (survives container reuse)")
    L.append(f'printf %s "$CMD" > "$SB_DIR/{CMD_FILE_NAME}"')
    L.append("")
    L.append("# Host-side pre-hook (firewall rules, etc.)")
    L.append(f'if [[ -f "$SB_DIR/{PRE_SCRIPT_NAME}" ]]; then')
    L.append(f'  bash "$SB_DIR/{PRE_SCRIPT_NAME}"')
    L.append("fi")
    L.append("cleanup() {")
    L.append(f'  if [[ -f "$SB_DIR/{POST_SCRIPT_NAME}" ]]; then')
    L.append(f'    bash "$SB_DIR/{POST_SCRIPT_NAME}"')
    L.append("  fi")
    L.append("}")
    L.append("trap cleanup EXIT")
    L.append("")
    if force_init:
        L.append("# --force-init: drop the init marker so it re-runs on next start")
        L.append(f"rm -f {shlex.quote(str(marker_host))}")
        if openspec:
            L.append(f"rm -f {shlex.quote(str(openspec_marker_host))}")
        L.append("")
    L.append("# Reuse an existing container for this workspace, else create a fresh one")
    L.append('if docker inspect "$CONTAINER" >/dev/null 2>&1; then')
    L.append('  if [[ "$(docker inspect -f \'{{.State.Status}}\' "$CONTAINER")" == "running" ]]; then')
    L.append('    docker attach "$CONTAINER"')
    L.append("  else")
    L.append('    docker start -ai "$CONTAINER"')
    L.append("  fi")
    L.append("  exit $?")
    L.append("fi")
    L.append("")
    L.append("# Fresh container: nothing is installed yet, so always re-run init")
    L.append(f"rm -f {shlex.quote(str(marker_host))}")
    if openspec:
        L.append(f"rm -f {shlex.quote(str(openspec_marker_host))}")
    L.append("")
    L.append("run_flags=(-i)")
    L.append("[[ -t 0 ]] && run_flags=(-it)")
    L.append("")
    L.append("run_args=(")
    L.append("  --hostname sandbox-code")
    L.append('  --name "$CONTAINER"')
    L.append('  -v "$WORKSPACE:/workspace"')
    L.append(f"  -v {shlex.quote(str(CONFIG_DIR))}:/home/ubuntu/.config/opencode")
    L.append(f"  -v {shlex.quote(str(DATA_DIR))}:/home/ubuntu/.local/share/opencode")
    L.append("  -e HOME=/home/ubuntu")
    L.append("  -e " + shlex.quote(f'TERM={os.environ.get("TERM", "xterm-256color")}'))
    L.append("  -e " + shlex.quote(f'LANG={os.environ.get("LANG", "C.UTF-8")}'))
    L.append("  -e " + shlex.quote(f'LC_ALL={os.environ.get("LC_ALL", "C.UTF-8")}'))
    L.append("  -w /workspace")
    L.append(")")

    if github:
        L.append("")
        L.append("# GitHub + SSH credentials (SECURITY: token and keys visible to agent)")
        L.append(f'[[ -d {shlex.quote(str(GH_DIR))} ]] && '
                 f'run_args+=(-v {shlex.quote(str(GH_DIR))}:/home/ubuntu/.config/gh)')
        L.append(f'[[ -d {shlex.quote(str(SSH_DIR))} ]] && '
                 f'run_args+=(-v {shlex.quote(str(SSH_DIR))}:/home/ubuntu/.ssh:ro)')
    elif ssh:
        L.append("")
        L.append("# SSH keys (SECURITY: private keys visible to the agent)")
        L.append(f'[[ -d {shlex.quote(str(SSH_DIR))} ]] && '
                 f'run_args+=(-v {shlex.quote(str(SSH_DIR))}:/home/ubuntu/.ssh:ro)')

    L.append("")
    L.append("# Forward API keys that are set in the host environment")
    L.append("for _var in " + " ".join(API_KEY_VARS) + "; do")
    L.append('  [[ -n "${!_var:-}" ]] && run_args+=(-e "$_var")')
    L.append("done")

    if x11:
        L.append("")
        L.append("# X11 / Wayland for clipboard (SECURITY: host display access)")
        L.append('if [[ -n "${DISPLAY:-}" ]]; then')
        L.append('  run_args+=(-e "DISPLAY=$DISPLAY" -v /tmp/.X11-unix:/tmp/.X11-unix)')
        L.append("fi")
        L.append('if [[ -n "${XAUTHORITY:-}" ]]; then')
        L.append('  run_args+=(-e "XAUTHORITY=$XAUTHORITY" -v "$XAUTHORITY:$XAUTHORITY:ro")')
        L.append("fi")
        L.append('if [[ -f "$HOME/.Xauthority" ]]; then')
        L.append('  run_args+=(-v "$HOME/.Xauthority:/home/ubuntu/.Xauthority:ro" '
                 '-e XAUTHORITY=/home/ubuntu/.Xauthority)')
        L.append("fi")
        L.append('if [[ -n "${WAYLAND_DISPLAY:-}" ]]; then')
        L.append('  _rt="${XDG_RUNTIME_DIR:-/run/user/1000}"')
        L.append('  run_args+=(-e "WAYLAND_DISPLAY=$WAYLAND_DISPLAY" '
                 '-v "$_rt/$WAYLAND_DISPLAY:/tmp/$WAYLAND_DISPLAY" -e XDG_RUNTIME_DIR=/tmp)')
        L.append("fi")

    if network_arg:
        L.append("")
        net_parts = ["--network", shlex.quote(network_arg)]
        net_parts += [shlex.quote(a) for a in dns_args]
        L.append("run_args+=(" + " ".join(net_parts) + ")")

    if no_git:
        git_repo = _ensure_project_git(workspace)
        L.append("")
        L.append("# --no-git: hide the real .git behind a disposable per-project repo")
        if git_repo is not None:
            L.append(f"run_args+=(-v {shlex.quote(str(git_repo))}:/workspace/.git)")
        else:
            L.append("run_args+=(--tmpfs /workspace/.git:ro,noexec,nosuid)")

    L.append("")
    L.append('docker run "${run_flags[@]}" "${run_args[@]}" sandbox-code:latest '
             '-c "$CONTAINER_CMD"')
    L.append("")

    run_path = _sb_file(workspace, RUN_SCRIPT_NAME)
    with open(run_path, "w") as f:
        f.write("\n".join(L))
    os.chmod(run_path, 0o755)

    print(f"[INFO] Wrote {SANDBOX_DIR}/{RUN_SCRIPT_NAME}")
    summary = f"container: {container} | features: {' '.join(features) or 'none'}"
    if filter_mode:
        summary += f" | network: {filter_mode} ({network_name})"
    elif network_arg:
        summary += f" | network: {network_arg}"
    print(f"[INFO] {summary}")

    _ensure_gitignore(workspace)


def _ensure_gitignore(workspace):
    """Append sandbox-code's generated files to .gitignore if missing."""
    # Ignore everything in .sandbox-code/ except the user-editable init script,
    # which stays committable.
    entries = [
        f"{SANDBOX_DIR}/*",
        f"!{SANDBOX_DIR}/{INIT_SCRIPT_NAME}",
    ]
    gitignore = os.path.join(workspace, ".gitignore")

    existing = set()
    ends_with_newline = True
    if os.path.isfile(gitignore):
        with open(gitignore) as f:
            content = f.read()
        existing = {ln.strip() for ln in content.splitlines()}
        ends_with_newline = content == "" or content.endswith("\n")

    missing = [e for e in entries if e not in existing]
    if not missing:
        return

    lines = ["# sandbox-code generated files", *missing, ""]
    prefix = "" if ends_with_newline else "\n"
    with open(gitignore, "a") as f:
        f.write(prefix + "\n".join(lines))
    print(f"[INFO] Updated .gitignore ({', '.join(missing)})")


def _clean_gitignore(workspace):
    """Remove sandbox-code's generated entries from .gitignore."""
    managed = {
        f"{SANDBOX_DIR}/*", f"!{SANDBOX_DIR}/{INIT_SCRIPT_NAME}",
        "# sandbox-code generated files",
    }
    gitignore = os.path.join(workspace, ".gitignore")
    if not os.path.isfile(gitignore):
        return

    with open(gitignore) as f:
        lines = f.read().splitlines()

    kept = [ln for ln in lines if ln.strip() not in managed]
    if len(kept) == len(lines):
        return

    with open(gitignore, "w") as f:
        f.write("\n".join(kept) + ("\n" if kept else ""))
    print("[INFO] Removed sandbox-code entries from .gitignore")


def _write_firewall_scripts(workspace, mode, network, iface, cidrs):
    os.makedirs(_sb_dir(workspace), exist_ok=True)
    pre_path = _sb_file(workspace, PRE_SCRIPT_NAME)
    post_path = _sb_file(workspace, POST_SCRIPT_NAME)
    with open(pre_path, "w") as f:
        f.write(_firewall_script(mode, "pre", network, iface, cidrs))
    os.chmod(pre_path, 0o755)
    with open(post_path, "w") as f:
        f.write(_firewall_script(mode, "post", network, iface, cidrs))
    os.chmod(post_path, 0o755)
    print(f"[INFO] Wrote {SANDBOX_DIR}/{PRE_SCRIPT_NAME} and "
          f"{SANDBOX_DIR}/{POST_SCRIPT_NAME} ({mode}, iface {iface})")


def _firewall_script(mode, phase, network, iface, cidrs):
    lines = [
        "#!/usr/bin/env bash",
        "# @generated-by: sandbox-code",
        f"# @mode: {mode}",
        f"# @network: {network}",
        f"# @iface: {iface}",
        f"# @phase: {phase}",
        "set -eo pipefail",
        "",
        f'IFACE="{iface}"',
        "CIDRS=(" + " ".join(f'"{c}"' for c in cidrs) + ")",
        "",
    ]

    if phase == "pre":
        if mode == "blacklist":
            lines += [
                "if command -v nft >/dev/null 2>&1; then",
                "  sudo nft add table inet sandbox-code 2>/dev/null || true",
                "  for hook in forward input; do",
                '    sudo nft add chain inet sandbox-code "${hook}_bl" '
                '"{ type filter hook $hook priority 0; }" 2>/dev/null || true',
                '    for cidr in "${CIDRS[@]}"; do',
                '      sudo nft add rule inet sandbox-code "${hook}_bl" '
                'iifname "$IFACE" ip daddr "$cidr" drop',
                "    done",
                "  done",
                "  exit 0",
                "fi",
                "",
                "for chain in FORWARD INPUT; do",
                '  for cidr in "${CIDRS[@]}"; do',
                '    sudo iptables -I "$chain" 1 -i "$IFACE" -d "$cidr" -j DROP '
                "-m comment --comment sandbox-code",
                "  done",
                "done",
            ]
        else:  # whitelist
            lines += [
                "if command -v nft >/dev/null 2>&1; then",
                "  sudo nft add table inet sandbox-code 2>/dev/null || true",
                "  for hook in forward input; do",
                '    sudo nft add chain inet sandbox-code "${hook}_wl" '
                '"{ type filter hook $hook priority 0; policy drop; }" 2>/dev/null || true',
                '    for cidr in "${CIDRS[@]}"; do',
                '      sudo nft add rule inet sandbox-code "${hook}_wl" '
                'iifname "$IFACE" ip daddr "$cidr" accept',
                "    done",
                "  done",
                "  exit 0",
                "fi",
                "",
                "for chain in FORWARD INPUT; do",
                '  for cidr in "${CIDRS[@]}"; do',
                '    sudo iptables -I "$chain" 1 -i "$IFACE" -d "$cidr" -j ACCEPT '
                "-m comment --comment sandbox-code",
                "  done",
                '  sudo iptables -A "$chain" -i "$IFACE" -d 0.0.0.0/0 -j DROP '
                "-m comment --comment sandbox-code",
                "done",
            ]
    else:  # post
        target = "DROP" if mode == "blacklist" else "ACCEPT"
        lines += [
            "if command -v nft >/dev/null 2>&1; then",
            "  sudo nft delete table inet sandbox-code 2>/dev/null || true",
            "fi",
            "",
            "for chain in FORWARD INPUT; do",
            '  for cidr in "${CIDRS[@]}"; do',
            f'    sudo iptables -D "$chain" -i "$IFACE" -d "$cidr" -j {target} '
            "-m comment --comment sandbox-code 2>/dev/null || true",
            "  done",
        ]
        if mode == "whitelist":
            lines.append(
                '  sudo iptables -D "$chain" -i "$IFACE" -d 0.0.0.0/0 -j DROP '
                "-m comment --comment sandbox-code 2>/dev/null || true"
            )
        lines.append("done")

    lines.append("")
    lines.append(f'echo "[sandbox-code] {phase}-hook applied ({mode})"')
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# run-phase helper
# ---------------------------------------------------------------------------

def _run_script(workspace, run_script, override=None):
    cmd = ["bash", run_script, *(override or [])]
    try:
        subprocess.run(cmd, cwd=workspace, env=os.environ, check=True)
    except subprocess.CalledProcessError as e:
        sys.exit(e.returncode)
    except KeyboardInterrupt:
        sys.exit(0)


def _read_metadata(path):
    meta = {}
    with open(path) as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if not line.startswith("#"):
                break
            m = re.match(r"#\s*@([\w-]+):\s*(.*)$", line)
            if m:
                meta[m.group(1)] = m.group(2).strip()
    return meta


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------

def _container_name(workspace):
    """Deterministic per-workspace container name: sandbox-code-<folder name>."""
    folder = os.path.basename(os.path.normpath(workspace)).lower()
    folder = re.sub(r"[^a-z0-9_.-]+", "-", folder).strip("._-")
    if not folder:
        folder = hashlib.sha256(workspace.encode()).hexdigest()[:10]
    return f"sandbox-code-{folder}"


def _ensure_project_git(workspace):
    """Return a disposable, per-workspace git repo to mount as .git."""
    if shutil.which("git") is None:
        return None

    digest = hashlib.sha256(os.path.abspath(workspace).encode()).hexdigest()[:16]
    repo_root = GITMIRROR_DIR / digest
    gitdir = repo_root / ".git"
    head = gitdir / "HEAD"

    if not head.exists():
        GITMIRROR_DIR.mkdir(parents=True, exist_ok=True)
        if repo_root.exists():
            shutil.rmtree(repo_root, ignore_errors=True)
        subprocess.run(["git", "init", "-q", str(repo_root)], check=True)
        subprocess.run(
            ["git", "-C", str(repo_root),
             "-c", "user.name=sandbox-code",
             "-c", "user.email=sandbox-code@localhost",
             "-c", "commit.gpgsign=false",
             "commit", "--allow-empty", "-q",
             "-m", "sandbox-code project marker"],
            check=True,
        )
    return gitdir


def _find_conf(workspace, script_dir, mode):
    """Locate <mode>-networks.conf, preferring the workspace copy."""
    ws_conf = os.path.join(workspace, f"{mode}-networks.conf")
    if os.path.isfile(ws_conf):
        return ws_conf
    return os.path.join(script_dir, FIREWALL_SUBDIR, f"{mode}-networks.conf")


def _ensure_network(conf_path):
    """Create the filter network if missing. Return (name, iface, cidrs)."""
    network, subnet, cidrs = _load_filter_config(conf_path)

    result = subprocess.run(
        ["docker", "network", "inspect", network],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        subprocess.run(
            ["docker", "network", "create", "-d", "bridge",
             "--subnet", subnet, network],
            check=True,
        )
        print(f"[INFO] Created Docker network '{network}'")

    return network, _bridge_iface(network), cidrs


def _bridge_iface(network):
    result = subprocess.run(
        ["docker", "network", "inspect", network,
         "--format", "{{index .Options \"com.docker.network.bridge.name\"}}"],
        capture_output=True, text=True, check=True,
    )
    iface = result.stdout.strip()
    if iface:
        return iface
    result = subprocess.run(
        ["docker", "network", "inspect", network,
         "--format", "{{.Id}}"],
        capture_output=True, text=True, check=True,
    )
    return f"br-{result.stdout.strip()[:12]}"


def _nft_available():
    return shutil.which("nft") is not None


def _load_filter_config(path):
    if not os.path.isfile(path):
        print(f"[ERROR] Config file not found: {path}", file=sys.stderr)
        sys.exit(1)
    lines = []
    with open(path) as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            lines.append(line)
    if len(lines) < 3:
        print(f"[ERROR] Config file too short ({len(lines)} lines, need at least 3)",
              file=sys.stderr)
        sys.exit(1)
    return lines[0], lines[1], lines[2:]


# -- iptables/nft constants --------------------------------------------------

_TAG = "sandbox-code"
_NFT_TABLE = f"inet {_TAG}"


def _run_shell(text):
    """Run a generated firewall script on the host (sudo lives inside it)."""
    subprocess.run(["bash", "-c", text], env=os.environ)


if __name__ == "__main__":
    main()
