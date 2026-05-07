from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path


DEFAULT_EXPERIMENT_ROOT = "/srv/ai-data/ailauncher/experiments"
DEFAULT_LLAMA_CPP_REPO = "https://github.com/ggml-org/llama.cpp.git"
DEFAULT_CONTAINER_IMAGE = "nvidia/cuda:12.8.0-devel-ubuntu24.04"


def _safe_print(text: str, *, stream=sys.stdout, end: str = "\n") -> None:
    try:
        print(text, file=stream, end=end)
    except UnicodeEncodeError:
        encoded = text.encode(stream.encoding or "utf-8", "replace")
        stream.buffer.write(encoded)
        stream.buffer.write(end.encode(stream.encoding or "utf-8", "replace"))
        stream.flush()


def _read_server_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.strip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _remote_script(
    *,
    execute_build: bool,
    build_mode: str,
    experiment_root: str,
    llama_cpp_repo: str,
    container_image: str,
    container_cpus: str,
    container_memory: str,
    model_path: str | None,
    bench_prompt: int,
    bench_generate: int,
) -> str:
    build_flag = "1" if execute_build else "0"
    model_literal = shlex.quote(model_path or "")
    return f"""#!/usr/bin/env bash
set -Eeuo pipefail

EXECUTE_BUILD={build_flag}
BUILD_MODE={shlex.quote(build_mode)}
EXPERIMENT_ROOT={shlex.quote(experiment_root)}
LLAMA_CPP_REPO={shlex.quote(llama_cpp_repo)}
CONTAINER_IMAGE={shlex.quote(container_image)}
CONTAINER_CPUS={shlex.quote(container_cpus)}
CONTAINER_MEMORY={shlex.quote(container_memory)}
MODEL_PATH={model_literal}
BENCH_PROMPT={bench_prompt}
BENCH_GENERATE={bench_generate}
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="$EXPERIMENT_ROOT/llama-cpp-sm-auto-$STAMP"
RUN_LOG="$RUN_ROOT/run.log"

say() {{
  printf '\\n== %s ==\\n' "$1"
}}

report_services() {{
  say "production services final"
  systemctl is-system-running || true
  for svc in ailauncher ollama docker sara-backend sara-backend-tunnel; do
    printf '%s=' "$svc"
    systemctl is-active "$svc" || true
  done
  systemctl --failed --no-pager || true
}}

trap report_services EXIT

run_or_note() {{
  if command -v "$1" >/dev/null 2>&1; then
    "$@"
  else
    echo "missing command: $1"
  fi
}}

detect_cuda_arch() {{
  local cap
  cap="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -n 1 | tr -d '[:space:].' || true)"
  if [ -n "$cap" ]; then
    echo "$cap"
    return 0
  fi

  local name
  name="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -n 1 || true)"
  case "$name" in
    *"RTX A4000"*) echo "86" ;;
    *"RTX 30"*) echo "86" ;;
    *"RTX 40"*) echo "89" ;;
    *"RTX 50"*) echo "120" ;;
    *"A100"*) echo "80" ;;
    *"H100"*) echo "90" ;;
    *) echo "" ;;
  esac
}}

say "production services before"
systemctl is-system-running || true
for svc in ailauncher ollama docker sara-backend sara-backend-tunnel; do
  printf '%s=' "$svc"
  systemctl is-active "$svc" || true
done
systemctl --failed --no-pager || true

say "hardware profile"
run_or_note hostnamectl || true
echo
run_or_note lscpu || true
echo
run_or_note free -h || true
echo
run_or_note df -h / "$EXPERIMENT_ROOT" 2>/dev/null || df -h / || true
echo
run_or_note nvidia-smi || true
echo
run_or_note nvidia-smi --query-gpu=name,compute_cap,memory.total,driver_version --format=csv || true

CUDA_ARCH="$(detect_cuda_arch)"
if [ -z "$CUDA_ARCH" ]; then
  echo "Could not detect CUDA architecture. The build plan will stop before compiling."
else
  echo "selected_cuda_arch=$CUDA_ARCH"
fi

say "toolchain profile"
for cmd in git cmake make gcc g++ nvidia-smi nvcc; do
  if path="$(command -v "$cmd" 2>/dev/null)"; then
    printf '%s=%s\\n' "$cmd" "$path"
  else
    printf '%s=missing\\n' "$cmd"
  fi
done
echo
cmake --version 2>/dev/null | head -n 1 || true
nvcc --version 2>/dev/null | tail -n 4 || true
echo
if command -v docker >/dev/null 2>&1; then
  docker --version || true
  docker info --format 'docker_runtimes={{{{json .Runtimes}}}}' 2>/dev/null || true
else
  echo "docker=missing"
fi

say "isolated build plan"
echo "run_root=$RUN_ROOT"
echo "repo=$LLAMA_CPP_REPO"
echo "cmake_flags=-DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=$CUDA_ARCH -DCMAKE_BUILD_TYPE=Release"
echo "build_mode=$BUILD_MODE"
if [ "$BUILD_MODE" = "container" ]; then
  echo "container_image=$CONTAINER_IMAGE"
  echo "container_limits=cpus:$CONTAINER_CPUS,memory:$CONTAINER_MEMORY"
fi
echo "production_paths_untouched=/opt/ailauncher,/etc/systemd/system/ailauncher.service,/etc/ailauncher/ailauncher.env"

if [ "$EXECUTE_BUILD" != "1" ]; then
  echo
  echo "dry_run=1"
  echo "No build was executed. Re-run with --execute-build to compile in the isolated run_root."
  exit 0
fi

if [ -z "$CUDA_ARCH" ]; then
  echo "Cannot build without a detected CUDA architecture." >&2
  exit 2
fi

mkdir -p "$RUN_ROOT"

if [ "$BUILD_MODE" = "container" ]; then
  if ! command -v docker >/dev/null 2>&1; then
    echo "Required command missing for container build: docker" >&2
    exit 3
  fi

  say "building llama.cpp in CUDA container sandbox"
cat > "$RUN_ROOT/container-build.sh" <<'CONTAINER_BUILD'
#!/usr/bin/env bash
set -Eeuo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends ca-certificates git cmake build-essential
git clone --depth 1 "$LLAMA_CPP_REPO" /work/llama.cpp

mkdir -p /tmp/cuda-stubs
if [ -f /usr/local/cuda/lib64/stubs/libcuda.so ]; then
  ln -sf /usr/local/cuda/lib64/stubs/libcuda.so /tmp/cuda-stubs/libcuda.so
  ln -sf /usr/local/cuda/lib64/stubs/libcuda.so /tmp/cuda-stubs/libcuda.so.1
  export LIBRARY_PATH="/tmp/cuda-stubs:/usr/local/cuda/lib64/stubs:${{LIBRARY_PATH:-}}"
  export LD_LIBRARY_PATH="/tmp/cuda-stubs:/usr/local/cuda/lib64/stubs:${{LD_LIBRARY_PATH:-}}"
fi

cmake -S /work/llama.cpp -B /work/build \\
  -DGGML_CUDA=ON \\
  -DCMAKE_CUDA_ARCHITECTURES="$CUDA_ARCH" \\
  -DCMAKE_BUILD_TYPE=Release \\
  -DCMAKE_EXE_LINKER_FLAGS="-L/tmp/cuda-stubs -Wl,-rpath-link,/tmp/cuda-stubs" \\
  -DCMAKE_SHARED_LINKER_FLAGS="-L/tmp/cuda-stubs -Wl,-rpath-link,/tmp/cuda-stubs"
cmake --build /work/build --config Release --target llama-cli llama-server llama-bench -j "$(nproc)"
find /work/build -maxdepth 3 -type f \\( -name 'llama-cli' -o -name 'llama-server' -o -name 'llama-bench' \\) -print
CONTAINER_BUILD
  chmod +x "$RUN_ROOT/container-build.sh"

  docker run --rm \\
    --name "ailauncher-llama-cpp-build-$STAMP" \\
    --cpus "$CONTAINER_CPUS" \\
    --memory "$CONTAINER_MEMORY" \\
    --security-opt no-new-privileges:true \\
    -e LLAMA_CPP_REPO="$LLAMA_CPP_REPO" \\
    -e CUDA_ARCH="$CUDA_ARCH" \\
    -v "$RUN_ROOT:/work" \\
    -w /work \\
    "$CONTAINER_IMAGE" \\
    bash /work/container-build.sh 2>&1 | tee "$RUN_LOG"

  say "build artifacts"
  find "$RUN_ROOT/build" -maxdepth 3 -type f \\( -name 'llama-cli' -o -name 'llama-server' -o -name 'llama-bench' \\) -print

  echo "run_root=$RUN_ROOT"
  echo "run_log=$RUN_LOG"
  exit 0
fi

if [ "$BUILD_MODE" != "host" ]; then
  echo "Unknown build mode: $BUILD_MODE" >&2
  exit 4
fi

for cmd in git cmake nvidia-smi; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Required command missing: $cmd" >&2
    exit 3
  fi
done

if ! command -v nvcc >/dev/null 2>&1; then
  echo "Required command missing for CUDA build: nvcc" >&2
  echo "Install a CUDA toolkit or run this experiment inside a CUDA devel container." >&2
  exit 3
fi

say "building llama.cpp in sandbox"
git clone --depth 1 "$LLAMA_CPP_REPO" "$RUN_ROOT/llama.cpp"
cmake -S "$RUN_ROOT/llama.cpp" -B "$RUN_ROOT/build" \\
  -DGGML_CUDA=ON \\
  -DCMAKE_CUDA_ARCHITECTURES="$CUDA_ARCH" \\
  -DCMAKE_BUILD_TYPE=Release
cmake --build "$RUN_ROOT/build" --config Release -j "$(nproc)"

say "build artifacts"
find "$RUN_ROOT/build" -maxdepth 3 -type f \\( -name 'llama-cli' -o -name 'llama-server' -o -name 'llama-bench' \\) -print

if [ -n "$MODEL_PATH" ]; then
  say "optional benchmark"
  if [ ! -f "$MODEL_PATH" ]; then
    echo "model_path_not_found=$MODEL_PATH"
  elif [ -x "$RUN_ROOT/build/bin/llama-bench" ]; then
    "$RUN_ROOT/build/bin/llama-bench" -m "$MODEL_PATH" -p "$BENCH_PROMPT" -n "$BENCH_GENERATE" -ngl 999 || true
  else
    echo "llama-bench binary not found in expected path"
  fi
else
  say "optional benchmark"
  echo "No --model-path was provided, so only compilation was tested."
fi

"""


def _run_with_paramiko(
    *,
    host: str,
    port: int,
    user: str,
    password: str | None,
    script: str,
    use_sudo: bool,
) -> int:
    try:
        import paramiko
    except ImportError as exc:
        raise SystemExit("paramiko no esta instalado; usa --print-script y ejecutalo por SSH.") from exc

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host,
        port=port,
        username=user,
        password=password,
        timeout=20,
        banner_timeout=20,
        auth_timeout=20,
    )
    try:
        command = "sudo -S -p '' bash -s" if use_sudo else "bash -s"
        stdin, stdout, stderr = client.exec_command(command, timeout=None)
        if use_sudo:
            if password is None:
                raise SystemExit("--use-sudo requiere password SSH o sudo disponible sin password.")
            stdin.write(password + "\n")
        stdin.write(script)
        stdin.channel.shutdown_write()
        for line in iter(stdout.readline, ""):
            _safe_print(line, end="")
        err = stderr.read().decode("utf-8", "replace")
        if err:
            _safe_print(err, stream=sys.stderr, end="")
        return stdout.channel.recv_exit_status()
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audita una GPU remota y, opcionalmente, compila llama.cpp en un sandbox."
    )
    parser.add_argument("--server-file", type=Path, help="Archivo con DEPLOY_SSH_*")
    parser.add_argument("--host", help="Host o IP del servidor")
    parser.add_argument("--user", help="Usuario SSH")
    parser.add_argument("--port", type=int, default=22, help="Puerto SSH")
    parser.add_argument("--password", help="Password SSH. Si se omite, se intenta llave/agent.")
    parser.add_argument(
        "--use-sudo",
        action="store_true",
        help="Ejecuta el script remoto con sudo. Util para escribir en /srv/ai-data.",
    )
    parser.add_argument("--experiment-root", default=DEFAULT_EXPERIMENT_ROOT)
    parser.add_argument("--llama-cpp-repo", default=DEFAULT_LLAMA_CPP_REPO)
    parser.add_argument(
        "--build-mode",
        choices=["container", "host"],
        default="container",
        help="Modo de compilacion. Por seguridad, el default usa un contenedor CUDA.",
    )
    parser.add_argument("--container-image", default=DEFAULT_CONTAINER_IMAGE)
    parser.add_argument("--container-cpus", default="12")
    parser.add_argument("--container-memory", default="16g")
    parser.add_argument("--model-path", help="Ruta remota a un GGUF para benchmark opcional")
    parser.add_argument("--bench-prompt", type=int, default=512)
    parser.add_argument("--bench-generate", type=int, default=128)
    parser.add_argument(
        "--execute-build",
        action="store_true",
        help="Compila llama.cpp. Sin este flag solo imprime auditoria y plan.",
    )
    parser.add_argument(
        "--print-script",
        action="store_true",
        help="Imprime el script remoto sin conectarse por SSH.",
    )
    args = parser.parse_args()

    if args.server_file:
        cfg = _read_server_file(args.server_file)
        args.host = args.host or cfg.get("DEPLOY_SSH_HOST")
        args.user = args.user or cfg.get("DEPLOY_SSH_USER")
        args.port = args.port if args.port != 22 else int(cfg.get("DEPLOY_SSH_PORT", args.port))
        args.password = args.password or cfg.get("DEPLOY_SSH_PASSWORD")

    script = _remote_script(
        execute_build=args.execute_build,
        build_mode=args.build_mode,
        experiment_root=args.experiment_root,
        llama_cpp_repo=args.llama_cpp_repo,
        container_image=args.container_image,
        container_cpus=args.container_cpus,
        container_memory=args.container_memory,
        model_path=args.model_path,
        bench_prompt=args.bench_prompt,
        bench_generate=args.bench_generate,
    )

    if args.print_script:
        print(script)
        return

    missing = [name for name in ("host", "user") if getattr(args, name) is None]
    if missing:
        raise SystemExit(f"Faltan parametros SSH: {', '.join(missing)}")

    result = _run_with_paramiko(
        host=args.host,
        port=args.port,
        user=args.user,
        password=args.password,
        script=script,
        use_sudo=args.use_sudo,
    )
    raise SystemExit(result)


if __name__ == "__main__":
    main()
