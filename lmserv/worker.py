from __future__ import annotations
import asyncio
import signal
import subprocess
import uuid
import logging
import os # Para os.cpu_count() si lo usas

from lmserv.config import Config # Asegúrate que esta importación es correcta

logger = logging.getLogger(__name__)

async def _stream_reader(stream, queue: asyncio.Queue, worker_id: str, stream_name: str, proc_control_event: asyncio.Event):
    loop = asyncio.get_event_loop()
    try:
        while not proc_control_event.is_set():
            # Usar readline() es apropiado si esperas que llama-cli envíe datos línea por línea
            # o al menos fragmentos terminados por \n cuando hace flush.
            # Si llama-cli envía tokens individuales sin \n, readline() podría bloquearse
            # hasta que llegue un \n o se cierre el stream.
            # Para un verdadero streaming token a token (char a char a veces), se necesitaría read().
            # Pero readline() es común y suele funcionar bien si llama-cli hace buffering de línea.
            line = await loop.run_in_executor(None, stream.readline)
            if not line:
                logger.debug(f"[{worker_id}/{stream_name}] EOF detected in _stream_reader.")
                await queue.put((stream_name, None)) # None significa EOF
                break
            # rstrip() es bueno para quitar el newline final si existe,
            # pero si la línea es un token parcial sin newline, no hará nada.
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
        self.reverse_prompt_marker: str = "\n<|LMSERV_USER_INPUT_START|>\n"
        self.proc_control_event = asyncio.Event()
        self.instance_output_queue: asyncio.Queue[tuple[str, str | None]] | None = None
        self.instance_stdout_reader_task: asyncio.Task | None = None
        self.instance_stderr_reader_task: asyncio.Task | None = None
        logger.info(f"[{self.id}] Worker initialized. Reverse prompt marker for llama-cli: '{self.reverse_prompt_marker.strip()}'")

    async def spawn(self) -> None:
        logger.info(f"[{self.id}] Spawn requested.")
        self.proc_control_event.clear()
        cmd = [
            self.cfg.llama_bin,
            "-m", self.cfg.model_path,
            # Usa el gpu_idx de la config para el flag -mg (main_gpu)
            # Solo si es relevante (múltiples GPUs) y si gpu_idx es un índice válido (>=0)
            # Si solo tienes una GPU, -mg no es estrictamente necesario pero no hace daño poner 0.
        ]
        if self.cfg.gpu_idx >= 0: # Asumiendo que -1 o None significa no especificarlo
             cmd.extend(["-mg", str(self.cfg.gpu_idx)])
        
        # -ngl N: Offload N capas a GPU. Si es 0, se usa CPU.
        # Un número alto como 1000 (mayor que las capas del modelo) significa "todas las posibles".
        # cfg.vram_cap_mb no se usa directamente por llama-cli, es más una guía para tu sistema.
        # Lo importante es que -ngl no exceda la capacidad de la GPU.
        # Para gemma 4B, 100 capas es un buen default para intentar offload completo.
        cmd.extend(["-ngl", "100"]) # O un valor más dinámico si lo tienes.

        cmd.extend([
            "-i",
            "--interactive-first",
            "-n", str(self.cfg.max_tokens), # Usar max_tokens de la config para la longitud de generación por defecto
            "--reverse-prompt", self.reverse_prompt_marker.strip(),
            # Opcional: Añadir threads si es beneficioso y lo tienes en config
            # "-t", str(self.cfg.threads_llamacli_AQUI), # si tienes un param especifico para esto
            # Opcional: Context size si lo quieres configurar diferente al default del modelo
            # "-c", "4096",
            # Opcional: Log disable para llama-cli si quieres menos verbosidad de él
            # "--log-disable",
        ])
        
        logger.info(f"[{self.id}] Spawn command: {' '.join(cmd)}")

        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, # line-buffered
            encoding='utf-8', errors='replace'
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
        spawn_timeout = 45.0
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
                        except asyncio.QueueEmpty: break
                    err_msg = f"LlamaWorker {self.id} process died during spawn. RC: {self.proc.returncode}. Stderr: {' // '.join(stderr_msg_list)}"
                    logger.error(err_msg)
                    raise RuntimeError(err_msg)

                if spawn_local_proc_event.is_set() and not initial_setup_complete:
                    q_messages = []
                    while not spawn_local_output_queue.empty():
                        try: q_messages.append(spawn_local_output_queue.get_nowait())
                        except asyncio.QueueEmpty: break
                    logger.error(f"[{self.id}] Spawn readers encountered issues before setup completion. Drained queue: {q_messages}")
                    err_msg = f"LlamaWorker {self.id} stream reader failed or process died during spawn before ready marker."
                    logger.error(err_msg)
                    raise RuntimeError(err_msg)
                
                try:
                    stream_name, line = await asyncio.wait_for(spawn_local_output_queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue

                if line is None:
                    spawn_local_proc_event.set()
                    stderr_output_on_eof = []
                    while not spawn_local_output_queue.empty():
                        try:
                            s_name_eof, l_line_eof = spawn_local_output_queue.get_nowait()
                            if s_name_eof == "stderr_spawn": stderr_output_on_eof.append(l_line_eof)
                        except asyncio.QueueEmpty: break
                    logger.error(f"[{self.id}] Stderr content on EOF during spawn for {stream_name}: {' // '.join(filter(None,stderr_output_on_eof))}")
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
                        logger.info(f"[{self.id}] llama-cli is now waiting for first input due to --interactive-first.")
                        initial_setup_complete = True
                        break 
                elif stream_name == "stdout_spawn":
                    logger.debug(f"[{self.id} SPAWN_STDOUT_UNEXPECTED]: {line!r}")

            if not initial_setup_complete:
                spawn_local_proc_event.set()
                stderr_msg_list_timeout = []
                if self.proc and self.proc.poll() is None:
                     while not spawn_local_output_queue.empty():
                        try:
                            s_name, l_line = spawn_local_output_queue.get_nowait()
                            if s_name == "stderr_spawn" and l_line and not l_line.startswith("ERROR_READER:"):
                                stderr_msg_list_timeout.append(l_line)
                        except asyncio.QueueEmpty: break
                rc_info = f"RC: {self.proc.returncode}" if self.proc and self.proc.poll() is not None else "still running or unknown RC"
                err_msg = f"LlamaWorker {self.id} timed out waiting for READY_MARKER ('{READY_MARKER_STDERR}') on stderr. {rc_info}. Last stderr lines: {' // '.join(stderr_msg_list_timeout)}"
                logger.error(err_msg)
                raise RuntimeError(err_msg)
        finally:
            spawn_local_proc_event.set()
            if spawn_stdout_reader_task and not spawn_stdout_reader_task.done(): spawn_stdout_reader_task.cancel()
            if spawn_stderr_reader_task and not spawn_stderr_reader_task.done(): spawn_stderr_reader_task.cancel()
            await asyncio.gather(spawn_stdout_reader_task, spawn_stderr_reader_task, return_exceptions=True)
            logger.debug(f"[{self.id}] Spawn-specific stream readers cleaned up.")

        if not initial_setup_complete :
            if self.proc and self.proc.poll() is None:
                logger.error(f"[{self.id}] Spawn did not complete successfully, attempting to kill process {self.proc.pid}.")
                self.proc.kill()
            self.proc = None
            raise RuntimeError(f"LlamaWorker {self.id} spawn did not complete successfully (internal logic error).")

        self.instance_output_queue = asyncio.Queue()
        self.instance_stdout_reader_task = asyncio.create_task(
            _stream_reader(self.proc.stdout, self.instance_output_queue, self.id, "stdout", self.proc_control_event)
        )
        self.instance_stderr_reader_task = asyncio.create_task(
            _stream_reader(self.proc.stderr, self.instance_output_queue, self.id, "stderr", self.proc_control_event)
        )
        logger.info(f"[{self.id}] Spawn successful. Instance readers started. Worker ready for inference.")

    async def infer(self, prompt: str) -> asyncio.AsyncIterator[str]:
        logger.info(f"[{self.id}] Infer request for prompt: {prompt[:100]!r}...")
        if not self.proc or self.proc.poll() is not None or self.proc_control_event.is_set() or not self.instance_output_queue:
            proc_status = "N/A"
            if self.proc: proc_status = f"PID: {self.proc.pid}, RC: {self.proc.poll()}"
            err_msg = (f"LlamaWorker {self.id} is not operational for infer. "
                       f"Proc: {proc_status}, ControlEventSet: {self.proc_control_event.is_set()}, "
                       f"OutputQueueExists: {self.instance_output_queue is not None}")
            logger.error(err_msg); raise RuntimeError(err_msg)

        assert self.proc.stdin

        prompt_to_send = prompt.strip() + "\n"
        
        logger.debug(f"[{self.id}] Sending prompt to stdin: {prompt_to_send!r}")
        try:
            self.proc.stdin.write(prompt_to_send)
            self.proc.stdin.flush()
        except (OSError, BrokenPipeError) as e:
            logger.error(f"[{self.id}] Error writing to llama-cli stdin: {e!r}. Marking worker as dead.")
            self.proc_control_event.set(); raise RuntimeError(f"LlamaWorker {self.id} stdin broken: {e!r}") from e

        lines_yielded = 0
        first_output_timeout = 180.0 
        subsequent_output_timeout = 60.0
        
        output_queue = self.instance_output_queue
        time_of_last_activity = asyncio.get_event_loop().time()
        first_token_received = False
        
        # Para manejar el eco del prompt de llama-cli
        # llama-cli a veces hace un eco del prompt que se le envía.
        # Necesitamos identificarlo y no enviarlo como parte de la respuesta.
        # El eco puede ser la línea exacta del prompt o puede tener espacios adicionales.
        # También, el prompt puede tener múltiples líneas. Comparamos la primera línea.
        prompt_first_line_stripped = prompt.strip().split('\n')[0].strip()
        is_prompt_echo_possible = True # Flag para solo chequear el eco al principio

        try:
            while not self.proc_control_event.is_set():
                current_loop_time = asyncio.get_event_loop().time()
                elapsed_since_last_activity = current_loop_time - time_of_last_activity
                current_timeout_for_get = first_output_timeout if not first_token_received else subsequent_output_timeout
                remaining_timeout = max(0.1, current_timeout_for_get - elapsed_since_last_activity)

                if remaining_timeout <= 0.1 and elapsed_since_last_activity > current_timeout_for_get:
                    logger.warning(f"[{self.id}] Timeout ({current_timeout_for_get}s) for output exceeded. "
                                   f"Total wait: {elapsed_since_last_activity:.2f}s. Prompt: {prompt[:50]}...")
                    if not first_token_received:
                        logger.error(f"[{self.id}] No output/echo from llama-cli after {elapsed_since_last_activity:.2f}s.")
                        self.proc_control_event.set()
                    break

                try:
                    stream_name, line = await asyncio.wait_for(output_queue.get(), timeout=remaining_timeout)
                    time_of_last_activity = asyncio.get_event_loop().time()
                except asyncio.TimeoutError:
                    logger.info(f"[{self.id}] Timeout ({remaining_timeout:.2f}s) on output_queue.get().")
                    if not first_token_received:
                        logger.warning(f"[{self.id}] No output/echo from llama-cli after initial timeout for prompt: {prompt[:50]}...")
                        self.proc_control_event.set()
                    break

                if line is None: 
                    logger.warning(f"[{self.id}] EOF received from {stream_name} during infer. Signaling proc_control_event.")
                    self.proc_control_event.set(); break

                if isinstance(line, str) and line.startswith("ERROR_READER:"):
                    logger.error(f"[{self.id}] Reader error from {stream_name} during infer: {line}")
                    self.proc_control_event.set(); break

                if stream_name == "stderr":
                    logger.info(f"[{self.id} INFER_STDERR]: {line!r}")
                    continue

                # stream_name es "stdout"
                logger.debug(f"[{self.id} INFER_STDOUT_RAW]: {line!r}") # Loguear lo que viene crudo (después de rstrip)

                # Si la línea actual (ya con rstrip) es el reverse prompt marker, terminamos.
                if line == self.reverse_prompt_marker.strip(): # Comparar con la versión sin \n
                    logger.info(f"[{self.id}] Reverse prompt marker '{self.reverse_prompt_marker.strip()}' detected. Ending inference.")
                    break 

                # Manejo del eco del prompt
                if is_prompt_echo_possible:
                    # Comprobar si la línea actual es parte del eco del prompt.
                    # A veces llama-cli añade el prompt al inicio de su salida.
                    # prompt_first_line_stripped es la primera línea del prompt del usuario, sin espacios extra.
                    # line ya tiene rstrip("\n") aplicado.
                    if line.strip() == prompt_first_line_stripped:
                        logger.debug(f"[{self.id}] Skipping echo of prompt line: {line!r}")
                        is_prompt_echo_possible = False # Ya no buscaremos más eco del prompt inicial
                        continue
                    else:
                        # Si la primera línea de stdout no es el eco, entonces ya no esperamos un eco.
                        is_prompt_echo_possible = False
                
                # Si no es el reverse prompt ni el eco, es un token de la respuesta.
                # `line` ya tiene `rstrip("\n")` del `_stream_reader`.
                # Para streaming, el cliente concatenará estos fragmentos.
                # Si llama-cli envía tokens uno por uno sin \n, `line` será ese token.
                # Si envía fragmentos más largos con \n, `line` será ese fragmento sin el \n final.
                yield line
                lines_yielded += 1
                if not first_token_received:
                    first_token_received = True
                    logger.info(f"[{self.id}] First token received for prompt: {prompt[:50]}...")
        
        except Exception as e:
            logger.error(f"[{self.id}] Exception during infer loop: {e!r}")
            self.proc_control_event.set()
            raise
        finally:
            logger.info(f"[{self.id}] Infer loop finished. Lines yielded: {lines_yielded}.")
            if lines_yielded == 0 and not first_token_received and not self.proc_control_event.is_set():
                logger.warning(f"[{self.id}] No lines yielded from stdout during infer for prompt: {prompt[:50]}... Possible stall or misconfiguration.")
    
    async def stop(self):
        logger.info(f"[{self.id}] Stop requested.")
        self.proc_control_event.set()

        tasks_to_cancel_and_await = []
        if self.instance_stdout_reader_task and not self.instance_stdout_reader_task.done():
            self.instance_stdout_reader_task.cancel()
            tasks_to_cancel_and_await.append(self.instance_stdout_reader_task)
        if self.instance_stderr_reader_task and not self.instance_stderr_reader_task.done():
            self.instance_stderr_reader_task.cancel()
            tasks_to_cancel_and_await.append(self.instance_stderr_reader_task)
        
        if tasks_to_cancel_and_await:
            logger.debug(f"[{self.id}] Waiting for instance stream reader tasks to cancel...")
            await asyncio.gather(*tasks_to_cancel_and_await, return_exceptions=True)
            logger.debug(f"[{self.id}] Instance stream reader tasks finished.")
        
        self.instance_stdout_reader_task = None
        self.instance_stderr_reader_task = None
        if self.instance_output_queue:
            while not self.instance_output_queue.empty():
                try: self.instance_output_queue.get_nowait()
                except asyncio.QueueEmpty: break
        self.instance_output_queue = None

        if self.proc and self.proc.poll() is None:
            logger.info(f"[{self.id}] Terminating process {self.proc.pid}...")
            try:
                logger.debug(f"[{self.id}] Sending SIGINT to process {self.proc.pid}.")
                self.proc.send_signal(signal.SIGINT)
                try:
                    await asyncio.wait_for(asyncio.to_thread(self.proc.wait, timeout=5.0), timeout=5.5)
                    rc = self.proc.returncode
                    logger.info(f"[{self.id}] Process {self.proc.pid} terminated gracefully with SIGINT. RC: {rc}.")
                except (subprocess.TimeoutExpired, asyncio.TimeoutError):
                    logger.warning(f"[{self.id}] Process {self.proc.pid} did not terminate after SIGINT and timeout. Sending SIGTERM.")
                    self.proc.terminate()
                    try:
                        await asyncio.wait_for(asyncio.to_thread(self.proc.wait, timeout=3.0), timeout=3.5)
                        rc = self.proc.returncode
                        logger.info(f"[{self.id}] Process {self.proc.pid} terminated with SIGTERM. RC: {rc}.")
                    except (subprocess.TimeoutExpired, asyncio.TimeoutError):
                        logger.error(f"[{self.id}] Process {self.proc.pid} did not terminate after SIGTERM. Sending SIGKILL.")
                        self.proc.kill()
                        await asyncio.to_thread(self.proc.wait)
                        rc = self.proc.returncode
                        logger.info(f"[{self.id}] Process {self.proc.pid} killed. RC: {rc}.")
            except Exception as e_proc_stop:
                pid_val = self.proc.pid if self.proc else 'N/A'
                logger.error(f"[{self.id}] Exception during process stop for pid {pid_val}: {e_proc_stop!r}. Ensuring kill if still running.")
                if self.proc and self.proc.poll() is None:
                    self.proc.kill()
                    await asyncio.to_thread(self.proc.wait)
        elif self.proc:
             pid = self.proc.pid; rc = self.proc.returncode
             logger.info(f"[{self.id}] Process {pid} was already terminated before stop. RC: {rc}.")
        else:
            logger.info(f"[{self.id}] No process to stop.")

        self.proc = None
        logger.info(f"[{self.id}] Stop completed.")

