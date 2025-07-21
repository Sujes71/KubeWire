import asyncio
import socket
import subprocess

from pods.pod import Pod


class PodUI:
    def __init__(self, pod: Pod):
        self.pod = pod
        self.process: subprocess.Popen = None

    def get_service(self) -> str:
        return self.pod.get_service()

    def get_namespace(self) -> str:
        return self.pod.get_namespace()

    def get_context(self) -> str:
        return self.pod.get_context()

    def get_port(self) -> int:
        return self.pod.get_port()

    def is_running(self) -> bool:
        if self.process is None:
            return False
        try:
            poll_result = self.process.poll()
            if poll_result is None:
                return True
            else:
                self.process = None
                return False
        except Exception:
            self.process = None
            return False

    def _is_port_available(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return True
            except OSError:
                return False

    @staticmethod
    def _log_console(message):
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {message}")

    async def start(self) -> bool:
        if self.is_running():
            return True

        cmd = [
            "kubectl",
            "port-forward",
            f"--context={self.get_context()}",
            f"--namespace={self.get_namespace()}",
            f"service/{self.get_service()}",
            f"{self.get_port()}:80"
        ]

        if not self._is_port_available(self.get_port()):
            PodUI._log_console(f"❌ Port {self.get_port()} is already in use for {self.get_service()}")
            return False

        if self.process and not self.is_running():
            self.process = None

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True
            )

            await asyncio.sleep(1.5)

            if self.is_running():
                return True
            else:
                if self.process:
                    try:
                        stdout_data, stderr_data = self.process.communicate(timeout=1)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        stdout_data, stderr_data = self.process.communicate()

                    if stderr_data:
                        stderr_lower = stderr_data.lower()
                        if "unable to listen on port" in stderr_lower:
                            PodUI._log_console(f"❌ Port {self.get_port()} is already in use for {self.get_service()}")
                        elif "service" in stderr_lower and "not found" in stderr_lower:
                            PodUI._log_console(f"❌ Service '{self.get_service()}' not found in namespace '{self.get_namespace()}'")
                        elif "context" in stderr_lower and "not found" in stderr_lower:
                            PodUI._log_console(f"❌ Kubernetes context not found. Check kubectl configuration.")
                        elif "kubectl" in stderr_lower and "not found" in stderr_lower:
                            PodUI._log_console(f"❌ kubectl command not found. Please install kubectl.")

                self.process = None
                return False

        except FileNotFoundError:
            PodUI._log_console(f"❌ kubectl command not found. Please install kubectl.")
            return False
        except Exception as e:
            PodUI._log_console(f"❌ Unexpected error for {self.get_service()}: {e}")
            return False

    def stop(self) -> bool:
        if not self.is_running():
            return True

        try:
            if self.process:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
                self.process = None
                return True
        except Exception as e:
            print(f"❌ Error stopping {self.get_service()}: {e}")
            return False
