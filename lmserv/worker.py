from __future__ import annotations
import asyncio
import signal
import subprocess
import uuid
import logging

from lmserv.config import Config

logger = logging.getLogger(__name__)

async def _stream_reader(stream, queue: asyncio.Queue, worker_id: str, stream_name: str, proc_control_event: asyncio.Event):
    loop = asyncio.get_event_loop()
    try:
        while not proc_control_event.is_set():
            line = await loop.run_in_executor(None, stream.readline)
            if not line:
                logger.debug(f"[{worker_id}/{stream_name}] EOF detected in _stream_reader.")
                await queue.put((stream_name, None))
                break
            await queue.put((stream_name, line.rstrip("\n")))
    except Exception as e:
        if not proc_control_event.is_set():
            logger.error(f"[{worker_id}/{stream_name}] Exception in _stream_reader: {e!r}")
            await queue.put((stream_name, f"ERROR_READER: {e!r}"))
    finally:
        if not proc_control_event.is_set():
            logger.warning(f"[{worker_id}/{stream_name}] _stream_reader finished unexpectedly, signaling proc_control_event.")
            proc_control_event.set()
        logger.debug(f"[{worker_id}/{stream_name}] _stream_reader task ending.")

class LlamaWorker:
    def __init__(self, cfg: Config):
        self.id = uuid.uuid4().hex[:8]
        self.cfg = cfg
        self.proc: subprocess.Popen[str] | None = None
        self.subsequent_prompt_marker: str | None = None
        self.proc_control_event = asyncio.Event()
        self.instance_output_queue: asyncio.Queue[tuple[str, str | None]] | None = None
        self.instance_stdout_reader_task: asyncio.Task | None = None
        self.instance_stderr_reader_task: asyncio.Task | None = None
        logger.info(f"[{self.id}] Worker initialized. Subsequent prompt marker for stdout: '{self.subsequent_prompt_marker}'")

    async def spawn(self) -> None:
        logger.info(f"[{self.id}] Spawn requested.")
        self.proc_control_event.clear()
        cmd = [
            self.cfg.llama_bin,
            "-m", self.cfg.model_path,
            "-ngl", "100",
            "-i",
            "--interactive-first",
            "-n", str(self.cfg.max_tokens),
        ]
        logger.info(f"[{self.id}] Spawn command: {' '.join(cmd)}")

        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1
        )
        logger.info(f"[{self.id}] Process started. PID: {self.proc.pid if self.proc else 'N/A'}")

        spawn_local_output_queue = asyncio.Queue()
        spawn_local_proc_event = asyncio.Event()

        spawn_stdout_reader_task = asyncio.create_task(
            _stream_reader(self.proc.stdout, spawn_local_output_queue, self.id, "stdout_spawn", spawn_local_proc_event)
        )
        spawn_stderr_reader_task = asyncio.create_task(
            _stream_reader(self.proc.stderr, spawn_local_output_queue, self.id, "stderr_spawn", spawn_local_proc_event)
        )

        initial_setup_complete = False
        spawn_timeout = 30.0
        READY_MARKER_STDERR = "== Running in interactive mode. =="
        logger.info(f"[{self.id}] Waiting for ready marker ('{READY_MARKER_STDERR}') on stderr (timeout: {spawn_timeout}s)...")

        try:
            start_time = asyncio.get_event_loop().time()
            while asyncio.get_event_loop().time() - start_time < spawn_timeout:
                if self.proc.poll() is not None:
                    spawn_local_proc_event.set()
                    stderr_msg_list = []
                    while not spawn_local_output_queue.empty():
                        try:
                            s_name, l_line = spawn_local_output_queue.get_nowait()
                            if s_name == "stderr_spawn" and l_line and not l_line.startswith("ERROR_READER:"):
                                stderr_msg_list.append(l_line)
                        except asyncio.QueueEmpty:
                            break
                    err_msg = f"LlamaWorker {self.id} process died during spawn. RC: {self.proc.returncode}. Stderr: {' // '.join(stderr_msg_list)}"
                    logger.error(err_msg)
                    raise RuntimeError(err_msg)

                if spawn_local_proc_event.is_set():
                    err_msg = f"LlamaWorker {self.id} stream reader failed during spawn."
                    logger.error(err_msg)
                    raise RuntimeError(err_msg)
                try:
                    stream_name, line = await asyncio.wait_for(spawn_local_output_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                if line is None:
                    spawn_local_proc_event.set()
                    err_msg = f"LlamaWorker {self.id} stream {stream_name} closed unexpectedly (EOF) during spawn."
                    logger.error(err_msg)
                    raise RuntimeError(err_msg)

                if isinstance(line, str) and line.startswith("ERROR_READER:"):
                    spawn_local_proc_event.set()
                    err_msg = f"LlamaWorker {self.id} reader error from {stream_name} during spawn: {line}"
                    logger.error(err_msg)
                    raise RuntimeError(err_msg)

                if stream_name == "stderr_spawn":
                    logger.debug(f"[{self.id} SPAWN_STDERR]: {line!r}")
                    if READY_MARKER_STDERR in line:
                        logger.info(f"[{self.id}] READY_MARKER ('{READY_MARKER_STDERR}') DETECTED on stderr.")
                        initial_setup_complete = True
                        break
                elif stream_name == "stdout_spawn":
                    logger.debug(f"[{self.id} SPAWN_STDOUT]: {line!r}")

            if not initial_setup_complete:
                spawn_local_proc_event.set()
                err_msg = f"LlamaWorker {self.id} timed out waiting for READY_MARKER ('{READY_MARKER_STDERR}') on stderr."
                logger.error(err_msg)
                raise RuntimeError(err_msg)
        finally:
            spawn_local_proc_event.set()
            if not spawn_stdout_reader_task.done():
                spawn_stdout_reader_task.cancel()
            if not spawn_stderr_reader_task.done():
                spawn_stderr_reader_task.cancel()
            await asyncio.gather(spawn_stdout_reader_task, spawn_stderr_reader_task, return_exceptions=True)

        if not initial_setup_complete:
            if self.proc and self.proc.poll() is None:
                self.proc.kill()
            self.proc = None
            raise RuntimeError(f"LlamaWorker {self.id} spawn did not complete successfully (marker not found or error after finally).")

        self.instance_output_queue = asyncio.Queue()
        self.instance_stdout_reader_task = asyncio.create_task(
            _stream_reader(self.proc.stdout, self.instance_output_queue, self.id, "stdout", self.proc_control_event)
        )
        self.instance_stderr_reader_task = asyncio.create_task(
            _stream_reader(self.proc.stderr, self.instance_output_queue, self.id, "stderr", self.proc_control_event)
        )
        logger.info(f"[{self.id}] Spawn successful. Instance readers started.")
    
    async def infer(self, prompt: str) -> asyncio.AsyncIterator[str]:
        logger.info(f"[{self.id}] Infer request for prompt: {prompt[:100]!r}...")
        if not self.proc or self.proc.poll() is not None or self.proc_control_event.is_set() or not self.instance_output_queue:
            err_msg = f"LlamaWorker {self.id} is not operational. Proc: {self.proc}, Poll: {self.proc.poll() if self.proc else 'N/A'}, Event: {self.proc_control_event.is_set()}, Queue: {self.instance_output_queue is None}"
            logger.error(err_msg)
            raise RuntimeError(err_msg)

        assert self.proc.stdin
        
        logger.debug(f"[{self.id}] Sending prompt to stdin: {prompt!r}")
        self.proc.stdin.write(prompt + "\n")
        self.proc.stdin.flush()

        first_line_is_echo = True
        lines_yielded = 0
        first_output_timeout = 60.0
        subsequent_output_timeout = 5.0
        
        output_queue = self.instance_output_queue
        time_of_last_stdout_activity = asyncio.get_event_loop().time()

        try:
            while not self.proc_control_event.is_set():
                current_loop_time = asyncio.get_event_loop().time()
                
                if lines_yielded == 0 and first_line_is_echo:
                    elapsed_waiting_first = current_loop_time - time_of_last_stdout_activity
                    timeout_for_get = max(0.1, first_output_timeout - elapsed_waiting_first)
                else:
                    timeout_for_get = subsequent_output_timeout

                try:
                    stream_name, line = await asyncio.wait_for(output_queue.get(), timeout=timeout_for_get)
                except asyncio.TimeoutError:
                    logger.info(f"[{self.id}] Timeout ({timeout_for_get:.2f}s) on output_queue.get(). Assuming generation part ended or stalled.")
                    if lines_yielded == 0 and first_line_is_echo:
                        logger.warning(f"[{self.id}] No output/echo from llama-cli after {first_output_timeout}s for prompt: {prompt[:50]}...")
                    break

                if line is None:
                    logger.warning(f"[{self.id}] EOF received from {stream_name} during infer. Signaling proc_control_event.")
                    self.proc_control_event.set()
                    break

                if isinstance(line, str) and line.startswith("ERROR_READER:"):
                    logger.error(f"[{self.id}] Reader error from {stream_name} during infer: {line}")
                    self.proc_control_event.set()
                    break

                if stream_name == "stderr":
                    logger.info(f"[{self.id} INFER_STDERR]: {line!r}")
                    continue

                logger.debug(f"[{self.id} INFER_STDOUT]: {line!r}")
                time_of_last_stdout_activity = asyncio.get_event_loop().time()

                if first_line_is_echo:
                    if line.strip() == prompt.strip().split('\n')[0].strip():
                        logger.debug(f"[{self.id}] Skipping echo: {line!r}")
                        first_line_is_echo = False
                        continue
                    else:
                        first_line_is_echo = False

                if self.subsequent_prompt_marker and line.strip() == self.subsequent_prompt_marker.strip():
                    if lines_yielded > 0:
                        logger.info(f"[{self.id}] Subsequent prompt marker '{self.subsequent_prompt_marker}' detected. Ending inference.")
                        break
                    else:
                        logger.debug(f"[{self.id}] Subsequent prompt marker '{self.subsequent_prompt_marker}' detected before any yield. Ignoring.")
                        continue
                
                if line.strip() == "" and lines_yielded > 0:
                    logger.debug(f"[{self.id}] Skipping empty line from stdout after yielding data.")
                    continue

                yield line
                lines_yielded += 1
        
        finally:
            logger.info(f"[{self.id}] Infer loop finished. Lines yielded: {lines_yielded}.")
            if lines_yielded == 0 and not self.proc_control_event.is_set():
                logger.warning(f"[{self.id}] No lines yielded from stdout during infer for prompt: {prompt[:50]}...")

    async def stop(self):
        logger.info(f"[{self.id}] Stop requested.")
        self.proc_control_event.set()

        tasks_to_cancel = []
        if self.instance_stdout_reader_task and not self.instance_stdout_reader_task.done():
            tasks_to_cancel.append(self.instance_stdout_reader_task)
        if self.instance_stderr_reader_task and not self.instance_stderr_reader_task.done():
            tasks_to_cancel.append(self.instance_stderr_reader_task)
        
        for task in tasks_to_cancel:
            task.cancel()
        
        if tasks_to_cancel:
            try:
                await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
            except asyncio.CancelledError:
                pass
        
        self.instance_stdout_reader_task = None
        self.instance_stderr_reader_task = None
        self.instance_output_queue = None

        if self.proc and self.proc.poll() is None:
            logger.info(f"[{self.id}] Sending SIGINT to process {self.proc.pid}.")
            self.proc.send_signal(signal.SIGINT)
            try:
                await asyncio.wait_for(asyncio.to_thread(self.proc.wait), timeout=5.0)
                logger.info(f"[{self.id}] Process {self.proc.pid} terminated with RC: {self.proc.returncode if self.proc else 'N/A'}.")
            except asyncio.TimeoutError:
                logger.warning(f"[{self.id}] Process {self.proc.pid} did not terminate after SIGINT and 5s timeout. Killing.")
                if self.proc.poll() is None:
                    self.proc.kill()
            except Exception as e:
                logger.error(f"[{self.id}] Exception during process stop: {e!r}. Ensuring kill if still running.")
                if self.proc.poll() is None:
                    self.proc.kill()
        else:
            logger.info(f"[{self.id}] Process was not running or already stopped when stop was called.")
        self.proc = None
        logger.info(f"[{self.id}] Stop completed.")
