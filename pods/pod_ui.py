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

    async def start(self) -> bool:
        if self.is_running():
            print(f"Process for {self.get_service()} is already running\n")
            return True

        cmd = [
            "kubectl",
            "port-forward",
            f"--context={self.get_context()}",
            f"--namespace={self.get_namespace()}",
            f"service/{self.get_service()}",
            f"{self.get_port()}:80"
        ]

        print(f"Starting port-forward: {' '.join(cmd)}")

        if not self._is_port_available(self.get_port()):
            print(f"❌ Port-forward failed for {self.get_service()}")
            print(f"   Error: Local port {self.get_port()} is already in use. Cannot start port-forward.")
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
                print(f"✅ Port-forward started for {self.get_service()}:{self.get_port()}")
                return True
            else:
                if self.process:
                    try:
                        stdout_data, stderr_data = self.process.communicate(timeout=1)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        stdout_data, stderr_data = self.process.communicate()

                    print(f"❌ Port-forward failed for {self.get_service()}")

                    if stderr_data:
                        stderr_lower = stderr_data.lower()
                        if "unable to listen on port" in stderr_lower:
                            print(f"   Error: Local port {self.get_port()} is already in use. Cannot start port-forward.\n")
                        elif "service" in stderr_lower and "not found" in stderr_lower:
                            print(f"   Error: Service '{self.get_service()}' not found in namespace '{self.get_namespace()}'.\n")
                        elif "no endpoints available" in stderr_lower:
                            print(f"   Error: Service '{self.get_service()}' has no available endpoints. The pod may be down or not ready.\n")
                        elif "connection refused" in stderr_lower or "unable to forward" in stderr_lower:
                            print(f"   Error: Unable to connect to service '{self.get_service()}'. The pod may be down or not responding.\n")
                        elif "context" in stderr_lower and "not found" in stderr_lower:
                            print(f"   Error: Kubernetes context not found. Please check your kubectl configuration.\n")
                        elif "namespace" in stderr_lower and "not found" in stderr_lower:
                            print(f"   Error: Namespace '{self.get_namespace()}' not found in the current context.\n")
                        else:
                            print(f"   Error: {stderr_data.strip()}\n")
                    elif stdout_data:
                        print(f"   Output: {stdout_data.strip()}\n")
                    else:
                        print(f"   Error: Unknown error occurred. The service '{self.get_service()}' may be down or unreachable.\n")

                self.process = None
                return False

        except FileNotFoundError:
            print(f"❌ Port-forward failed for {self.get_service()}")
            print(f"   Error: kubectl command not found. Please make sure kubectl is installed and in your PATH.\n")
            return False
        except Exception as e:
            print(f"❌ Port-forward failed for {self.get_service()}")
            print(f"   Error: Unexpected error occurred: {e}\n")
            return False

    def stop(self) -> bool:
        if not self.is_running():
            print(f"No running process for {self.get_service()}")
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
                print(f"🛑 Stopped port-forward for {self.get_service()}")
                return True
        except Exception as e:
            print(f"❌ Error stopping port-forward for {self.get_service()}: {e}")
            return False
