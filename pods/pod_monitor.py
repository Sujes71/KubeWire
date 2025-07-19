import threading
import time
from typing import Set


class PodMonitor:
    def __init__(self, tui_instance):
        self.tui = tui_instance
        self.monitoring = False
        self.monitor_thread = None
        self.check_interval = 5
        self.recently_failed_pods: Set[str] = set()
        self.lock = threading.Lock()
        self.user_stopped_pods: Set[str] = set()

    def start_monitoring(self):
        if self.monitoring:
            return
        self.monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()

    def stop_monitoring(self):
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=1)

    def _monitor_loop(self):
        while self.monitoring:
            try:
                self._check_pods_status()
                time.sleep(self.check_interval)
            except Exception as e:
                print(f"❌ Error in pod monitor: {e}")
                time.sleep(self.check_interval)

    def _check_pods_status(self):
        if not self.tui.current_pods:
            return

        status_changed = False
        failed_pods = []

        with self.lock:
            for pod in self.tui.current_pods:
                pod_id = f"{pod.get_context()}/{pod.get_namespace()}/{pod.get_service()}"
                current_running = pod.is_running()
                was_running = getattr(pod, '_was_running', False)

                if pod_id not in self.user_stopped_pods:
                    if was_running and not current_running:
                        if pod_id not in self.recently_failed_pods:
                            self.recently_failed_pods.add(pod_id)
                            failed_pods.append(pod)
                            status_changed = True

                if was_running != current_running:
                    status_changed = True

                pod._was_running = current_running

                if current_running and pod_id in self.recently_failed_pods:
                    self.recently_failed_pods.remove(pod_id)
                    self.user_stopped_pods.discard(pod_id)
                    status_changed = True

        if status_changed and self.tui.current_context:
            self.tui.request_refresh()

    def mark_user_stopped(self, pod_id: str):
        with self.lock:
            self.user_stopped_pods.add(pod_id)
            self.recently_failed_pods.discard(pod_id)

    def mark_user_started(self, pod_id: str):
        with self.lock:
            self.user_stopped_pods.discard(pod_id)
            self.recently_failed_pods.discard(pod_id)

    def stop(self):
        self.stop_monitoring()
