"""Best-effort free-memory guard; never controls the production chat service."""
import argparse
import subprocess
import time

GPU = 'GPU-986b5314-77d6-6659-236a-6a76dbe59619'
UNITS = ('ailauncher-ocr.service', 'ailauncher-embeddings.service')


def free_mib():
    output = subprocess.check_output([
        'nvidia-smi', '-i', GPU, '--query-gpu=memory.free',
        '--format=csv,noheader,nounits',
    ], text=True, timeout=3)
    return int(output.strip())


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--require-free', type=int)
    args = parser.parse_args()
    if args.require_free is not None:
        available = free_mib()
        if available < args.require_free:
            raise SystemExit(f'Auxiliary startup refused: {available} MiB free; need {args.require_free}')
    else:
        while True:
            try:
                available = free_mib()
            except (subprocess.SubprocessError, ValueError):
                available = 0
            if available < 3072:
                # Leave a 1 GiB reaction margin above the requested 2 GiB floor.
                # A polled guard is not a hardware quota or an instantaneous guarantee.
                active = [unit for unit in UNITS if subprocess.run(
                    ['systemctl', 'is-active', '--quiet', unit], check=False).returncode == 0]
                if active:
                    print(f'GPU0 has {available} MiB free: stopping auxiliaries {active}', flush=True)
                    # Under memory pressure, graceful inference shutdown can
                    # wait for a CUDA kernel. Kill only these fixed auxiliary
                    # units immediately, then settle their systemd state.
                    subprocess.run(['systemctl', 'kill', '--signal=SIGKILL', *active], check=False, timeout=5)
                    subprocess.run(['systemctl', 'stop', '--no-block', *active], check=False, timeout=5)
            time.sleep(1)
