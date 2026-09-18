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
        help="Delete all persistent data before starting (API Keys, ...)",
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
        "--no-network",
        action="store_true",
        help="Disable all networking (--network none)",
    )
    parser.add_argument(
        "--network",
        type=str,
        default=None,
        help="Docker network to use (default: bridge)",
    )
    parser.add_argument(
        "--blacklist",
        action="store_true",
        help="Isolate from local/Tailscale subnets, allow internet",
    )
    parser.add_argument(
        "--whitelist",
        action="store_true",
        help="Allow only listed CIDRs, block everything else (inverted blacklist)",
    )
    parser.add_argument(
        "--clean-rules",
        action="store_true",
        help="Remove firewall rules created by --blacklist / --whitelist",
    )
    parser.add_argument(
        "--no-git",
        action="store_true",
        help="Hide .git directory (tmpfs over /workspace/.git)",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Command to run inside the container (default: opencode .)",
    )

    args = parser.parse_args()

    network_opts = [args.blacklist, args.whitelist, args.no_network, bool(args.network)]
    if sum(network_opts) > 1:
        pieces = []
        if args.blacklist:
            pieces.append("--blacklist")
        if args.whitelist:
            pieces.append("--whitelist")
        if args.no_network:
            pieces.append("--no-network")
        if args.network:
            pieces.append("--network")
        parser.error(f"{', '.join(pieces)} are mutually exclusive")

    if args.clean_rules:
        _clean_all_rules(script_dir)
        return

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
        if "DISPLAY" in os.environ:
            docker_cmd.extend(["-e", f'DISPLAY={os.environ["DISPLAY"]}'])
            docker_cmd.extend(["-v", "/tmp/.X11-unix:/tmp/.X11-unix"])
            print("[INFO] X11 support enabled (DISPLAY={})".format(os.environ["DISPLAY"]))
        else:
            print("[WARNING] --x11 requested but DISPLAY not set in environment", file=sys.stderr)

        if "XAUTHORITY" in os.environ:
            docker_cmd.extend(["-e", f'XAUTHORITY={os.environ["XAUTHORITY"]}'])
            docker_cmd.extend(["-v", f'{os.environ["XAUTHORITY"]}:{os.environ["XAUTHORITY"]}'])

        xauth_path = pathlib.Path.home() / ".Xauthority"
        if xauth_path.exists():
            docker_cmd.extend(["-v", f"{xauth_path}:/home/ubuntu/.Xauthority:ro"])
            docker_cmd.extend(["-e", "XAUTHORITY=/home/ubuntu/.Xauthority"])

        if "WAYLAND_DISPLAY" in os.environ:
            runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "/run/user/1000")
            wayland_display = os.environ["WAYLAND_DISPLAY"]
            docker_cmd.extend(["-e", f'WAYLAND_DISPLAY={wayland_display}'])
            docker_cmd.extend(["-v", f"{runtime_dir}/{wayland_display}:/tmp/{wayland_display}"])
            docker_cmd.extend(["-e", "XDG_RUNTIME_DIR=/tmp"])
            print("[INFO] Wayland socket mounted for XWayland support")

    # --- Network isolation ---
    if args.blacklist or args.whitelist:
        mode = "blacklist" if args.blacklist else "whitelist"
        conf_path = os.path.join(script_dir, f"{mode}-networks.conf")
        network_name, subnet, cidrs = _load_filter_config(conf_path)

        result = subprocess.run(
            ["docker", "network", "inspect", network_name],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            subprocess.run(
                ["docker", "network", "create", "-d", "bridge",
                 "--subnet", subnet, network_name],
                check=True,
            )
            print(f"[INFO] Created Docker network '{network_name}'")

        _apply_filter_rules(mode, network_name, cidrs)

        docker_cmd.extend(["--network", network_name])
        docker_cmd.extend(["--dns", "1.1.1.1", "--dns", "8.8.8.8"])
    elif args.no_network:
        docker_cmd.extend(["--network", "none"])
    elif args.network:
        docker_cmd.extend(["--network", args.network])

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

    if args.no_git:
        docker_cmd.extend(["--tmpfs", "/workspace/.git:ro,noexec,nosuid"])

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


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

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


def _iptables_available():
    return shutil.which("iptables") is not None


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
        print(f"[ERROR] Config file too short ({len(lines)} lines, need at least 3)", file=sys.stderr)
        sys.exit(1)
    return lines[0], lines[1], lines[2:]


# -- rule helpers ------------------------------------------------------------

_TAG = "sandbox-code"
_IPTABLES_CHAINS = ("FORWARD", "INPUT")
_NFT_TABLE = f"inet {_TAG}"


def _rule_exists_iptables(chain, iface, cidr, action):
    rc = subprocess.run(
        ["sudo", "iptables", "-C", chain,
         "-i", iface, "-d", cidr, "-j", action,
         "-m", "comment", "--comment", _TAG],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode
    return rc == 0


def _rule_add_iptables(chain, iface, cidr, action):
    return subprocess.run(
        ["sudo", "iptables", "-I", chain, "1",
         "-i", iface, "-d", cidr, "-j", action,
         "-m", "comment", "--comment", _TAG],
    ).returncode


def _rule_del_iptables(chain, iface, cidr, action):
    return subprocess.run(
        ["sudo", "iptables", "-D", chain,
         "-i", iface, "-d", cidr, "-j", action,
         "-m", "comment", "--comment", _TAG],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode


# -- blacklist ---------------------------------------------------------------

def _add_blacklist_iptables(iface, cidrs):
    ok = True
    for chain in _IPTABLES_CHAINS:
        for cidr in cidrs:
            if not _rule_exists_iptables(chain, iface, cidr, "DROP"):
                if _rule_add_iptables(chain, iface, cidr, "DROP") != 0:
                    ok = False
    return ok


def _add_blacklist_nft(iface, cidrs):
    subprocess.run(["sudo", "nft", "add", "table", _NFT_TABLE],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ok = True
    for hook in ("forward", "input"):
        chain_name = f"{hook}_bl"
        subprocess.run(["sudo", "nft", "add", "chain", _NFT_TABLE, chain_name,
                        f"{{ type filter hook {hook} priority 0; }}"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for cidr in cidrs:
            rc = subprocess.run(
                ["sudo", "nft", "add", "rule", _NFT_TABLE, chain_name,
                 f"iifname {iface} ip daddr {cidr} drop"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            ).returncode
            if rc != 0:
                ok = False
    return ok


def _del_blacklist_iptables(iface, cidrs):
    for chain in _IPTABLES_CHAINS:
        for cidr in cidrs:
            _rule_del_iptables(chain, iface, cidr, "DROP")


# -- whitelist ---------------------------------------------------------------

def _add_whitelist_iptables(iface, cidrs):
    ok = True
    for chain in _IPTABLES_CHAINS:
        for cidr in cidrs:
            if not _rule_exists_iptables(chain, iface, cidr, "ACCEPT"):
                if _rule_add_iptables(chain, iface, cidr, "ACCEPT") != 0:
                    ok = False
        if not _rule_exists_iptables(chain, iface, "0.0.0.0/0", "DROP"):
            rc = subprocess.run(
                ["sudo", "iptables", "-A", chain,
                 "-i", iface, "-d", "0.0.0.0/0", "-j", "DROP",
                 "-m", "comment", "--comment", _TAG],
            ).returncode
            if rc != 0:
                ok = False
    return ok


def _add_whitelist_nft(iface, cidrs):
    subprocess.run(["sudo", "nft", "add", "table", _NFT_TABLE],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ok = True
    for hook in ("forward", "input"):
        chain_name = f"{hook}_wl"
        subprocess.run(["sudo", "nft", "add", "chain", _NFT_TABLE, chain_name,
                        f"{{ type filter hook {hook} priority 0; policy drop; }}"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for cidr in cidrs:
            rc = subprocess.run(
                ["sudo", "nft", "add", "rule", _NFT_TABLE, chain_name,
                 f"iifname {iface} ip daddr {cidr} accept"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            ).returncode
            if rc != 0:
                ok = False
    return ok


def _del_whitelist_iptables(iface, cidrs):
    for chain in _IPTABLES_CHAINS:
        for cidr in cidrs:
            _rule_del_iptables(chain, iface, cidr, "ACCEPT")
        _rule_del_iptables(chain, iface, "0.0.0.0/0", "DROP")


# -- orchestrator ------------------------------------------------------------

def _apply_filter_rules(mode, network, cidrs):
    try:
        iface = _bridge_iface(network)
    except subprocess.CalledProcessError:
        print(f"[ERROR] Cannot inspect network '{network}'", file=sys.stderr)
        return

    add_ipt, add_nft = (
        (_add_blacklist_iptables, _add_blacklist_nft) if mode == "blacklist"
        else (_add_whitelist_iptables, _add_whitelist_nft)
    )

    if _nft_available():
        if add_nft(iface, cidrs):
            print(f"[INFO] {mode} applied via nftables: {', '.join(cidrs)}")
            return
        if _iptables_available():
            print("[INFO] nftables failed, falling back to iptables")
            if add_ipt(iface, cidrs):
                print(f"[INFO] {mode} applied via iptables: {', '.join(cidrs)}")
                return

    if _iptables_available():
        if add_ipt(iface, cidrs):
            print(f"[INFO] {mode} applied via iptables: {', '.join(cidrs)}")
            return

    print(f"[WARNING] Could not apply {mode} firewall rules (sudo failed).", file=sys.stderr)


# -- cleanup -----------------------------------------------------------------

def _clean_all_rules(script_dir):
    cleaned = False

    for mode in ("blacklist", "whitelist"):
        conf_path = os.path.join(script_dir, f"{mode}-networks.conf")
        if not os.path.isfile(conf_path):
            continue
        network, _, cidrs = _load_filter_config(conf_path)
        try:
            iface = _bridge_iface(network)
        except subprocess.CalledProcessError:
            print(f"[INFO] Network '{network}' not found, skipping {mode} cleanup")
            continue

        if _iptables_available():
            fn_del = _del_blacklist_iptables if mode == "blacklist" else _del_whitelist_iptables
            fn_del(iface, cidrs)
            cleaned = True

    if _nft_available():
        subprocess.run(["sudo", "nft", "delete", "table", _NFT_TABLE],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cleaned = True

    if cleaned:
        print("[INFO] Firewall rules removed")
    else:
        print("[WARNING] No firewall tool (iptables/nft) available, nothing cleaned", file=sys.stderr)


if __name__ == "__main__":
    main()