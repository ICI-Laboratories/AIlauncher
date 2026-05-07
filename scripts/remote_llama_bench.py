from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path


DEFAULT_IMAGE = "nvidia/cuda:12.8.0-devel-ubuntu24.04"


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
    run_root: str,
    model_path: str,
    image: str,
    gpu_layers: list[int],
    prompt_tokens: int,
    generate_tokens: int,
    repetitions: int,
    cpus: str,
    memory: str,
    timeout_s: int,
) -> str:
    ngl_values = " ".join(str(value) for value in gpu_layers)
    return f"""#!/usr/bin/env bash
set -Eeuo pipefail

RUN_ROOT={shlex.quote(run_root)}
MODEL_PATH={shlex.quote(model_path)}
IMAGE={shlex.quote(image)}
NGL_VALUES={shlex.quote(ngl_values)}
PROMPT_TOKENS={prompt_tokens}
GENERATE_TOKENS={generate_tokens}
REPETITIONS={repetitions}
CPUS={shlex.quote(cpus)}
MEMORY={shlex.quote(memory)}
TIMEOUT_S={timeout_s}
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_DIR="$RUN_ROOT/benchmarks"
mkdir -p "$LOG_DIR"

say() {{
  printf '\\n== %s ==\\n' "$1"
}}

report_services() {{
  say "production services"
  systemctl is-system-running || true
  for svc in ailauncher ollama docker sara-backend sara-backend-tunnel; do
    printf '%s=' "$svc"
    systemctl is-active "$svc" || true
  done
  systemctl --failed --no-pager || true
  nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv,noheader || true
}}

trap report_services EXIT

say "benchmark inputs"
echo "run_root=$RUN_ROOT"
echo "model_path=$MODEL_PATH"
echo "image=$IMAGE"
echo "gpu_layers=$NGL_VALUES"
echo "prompt_tokens=$PROMPT_TOKENS"
echo "generate_tokens=$GENERATE_TOKENS"
echo "repetitions=$REPETITIONS"
echo "limits=cpus:$CPUS,memory:$MEMORY"

if [ ! -x "$RUN_ROOT/build/bin/llama-bench" ]; then
  echo "llama-bench not found or not executable: $RUN_ROOT/build/bin/llama-bench" >&2
  exit 2
fi
if [ ! -f "$MODEL_PATH" ]; then
  echo "model not found: $MODEL_PATH" >&2
  exit 2
fi

report_services

for NGL in $NGL_VALUES; do
  say "llama-bench ngl=$NGL"
  LOG="$LOG_DIR/llama-bench-$STAMP-ngl$NGL.log"
  docker run --rm \\
    --name "ailauncher-llama-bench-$STAMP-ngl$NGL" \\
    --cpus "$CPUS" \\
    --memory "$MEMORY" \\
    --memory-swap "$MEMORY" \\
    --device /dev/nvidiactl \\
    --device /dev/nvidia-uvm \\
    --device /dev/nvidia-uvm-tools \\
    --device /dev/nvidia0 \\
    --device /dev/nvidia1 \\
    -v /lib/x86_64-linux-gnu/libcuda.so.570.211.01:/usr/lib/x86_64-linux-gnu/libcuda.so.570.211.01:ro \\
    -v /lib/x86_64-linux-gnu/libcuda.so.1:/usr/lib/x86_64-linux-gnu/libcuda.so.1:ro \\
    -v /lib/x86_64-linux-gnu/libcuda.so:/usr/lib/x86_64-linux-gnu/libcuda.so:ro \\
    -v /lib/x86_64-linux-gnu/libnvidia-ml.so.570.211.01:/usr/lib/x86_64-linux-gnu/libnvidia-ml.so.570.211.01:ro \\
    -v /lib/x86_64-linux-gnu/libnvidia-ml.so.1:/usr/lib/x86_64-linux-gnu/libnvidia-ml.so.1:ro \\
    -v /lib/x86_64-linux-gnu/libnvidia-ml.so:/usr/lib/x86_64-linux-gnu/libnvidia-ml.so:ro \\
    -v /lib/x86_64-linux-gnu/libnvidia-ptxjitcompiler.so.570.211.01:/usr/lib/x86_64-linux-gnu/libnvidia-ptxjitcompiler.so.570.211.01:ro \\
    -v /lib/x86_64-linux-gnu/libnvidia-ptxjitcompiler.so.1:/usr/lib/x86_64-linux-gnu/libnvidia-ptxjitcompiler.so.1:ro \\
    -v /lib/x86_64-linux-gnu/libnvidia-ptxjitcompiler.so:/usr/lib/x86_64-linux-gnu/libnvidia-ptxjitcompiler.so:ro \\
    -v "$RUN_ROOT:/work:ro" \\
    -v "$MODEL_PATH:/model.gguf:ro" \\
    "$IMAGE" \\
    bash -lc 'export LD_LIBRARY_PATH=/work/build/bin:/usr/lib/x86_64-linux-gnu:/usr/local/cuda/lib64:$LD_LIBRARY_PATH; timeout "$0" /work/build/bin/llama-bench -m /model.gguf -p "$1" -n "$2" -ngl "$3" -r "$4"' \\
    "$TIMEOUT_S" "$PROMPT_TOKENS" "$GENERATE_TOKENS" "$NGL" "$REPETITIONS" 2>&1 | tee "$LOG"
  echo "log=$LOG"
done
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
        raise SystemExit("paramiko no esta instalado.") from exc

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
                raise SystemExit("--use-sudo requiere password o sudo sin password.")
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
    parser = argparse.ArgumentParser(description="Ejecuta llama-bench remoto en contenedor CUDA aislado.")
    parser.add_argument("--server-file", type=Path, help="Archivo con DEPLOY_SSH_*")
    parser.add_argument("--host")
    parser.add_argument("--user")
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--password")
    parser.add_argument("--use-sudo", action="store_true")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--gpu-layers", nargs="+", type=int, default=[4, 999])
    parser.add_argument("--prompt-tokens", type=int, default=64)
    parser.add_argument("--generate-tokens", type=int, default=16)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--cpus", default="8")
    parser.add_argument("--memory", default="28g")
    parser.add_argument("--timeout-s", type=int, default=420)
    parser.add_argument("--print-script", action="store_true")
    args = parser.parse_args()

    if args.server_file:
        cfg = _read_server_file(args.server_file)
        args.host = args.host or cfg.get("DEPLOY_SSH_HOST")
        args.user = args.user or cfg.get("DEPLOY_SSH_USER")
        args.port = args.port if args.port != 22 else int(cfg.get("DEPLOY_SSH_PORT", args.port))
        args.password = args.password or cfg.get("DEPLOY_SSH_PASSWORD")

    missing = [name for name in ("host", "user") if getattr(args, name) is None]
    if missing:
        raise SystemExit(f"Faltan parametros SSH: {', '.join(missing)}")

    script = _remote_script(
        run_root=args.run_root,
        model_path=args.model_path,
        image=args.image,
        gpu_layers=args.gpu_layers,
        prompt_tokens=args.prompt_tokens,
        generate_tokens=args.generate_tokens,
        repetitions=args.repetitions,
        cpus=args.cpus,
        memory=args.memory,
        timeout_s=args.timeout_s,
    )
    if args.print_script:
        print(script)
        return

    raise SystemExit(
        _run_with_paramiko(
            host=args.host,
            port=args.port,
            user=args.user,
            password=args.password,
            script=script,
            use_sudo=args.use_sudo,
        )
    )


if __name__ == "__main__":
    main()
