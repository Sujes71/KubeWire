import asyncio
import os
import subprocess
import sys
import threading
import time
from datetime import datetime

from config.config_manager import ConfigManager
from pods.pod_monitor import PodMonitor
from pods.sound_notifier import SoundNotifier


class KubeWireTUI:
    def __init__(self, contexts, context_statuses=None):
        self.contexts = contexts
        self.context_statuses = context_statuses or []
        self.current_context = None
        self.current_pods = []
        self.running = True
        self.pod_monitor = PodMonitor(self)
        self.display_update_flag = threading.Event()
        self.input_lock = threading.Lock()
        self.in_service_menu = False
        self.last_alert_time = 0
        self.alert_cooldown = 10
        self.current_input_prompt = ""
        self.refresh_requested = threading.Event()
        self.input_interrupted = False
        self.sound_notifier = SoundNotifier()
        self.sound_enabled = self.sound_notifier.is_sound_available()

        self.notified_disconnected_pods = set()

        for context_pods in self.contexts.values():
            for pod in context_pods:
                pod._was_running = False
                pod._is_starting = False

    @staticmethod
    def _log_console(message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {message}")

    def request_refresh(self):
        self.refresh_requested.set()

    def trigger_display_update(self):
        if self.in_service_menu:
            self.display_update_flag.set()

    def _display_update_thread(self):
        while self.running:
            if self.display_update_flag.wait(timeout=1):
                self.display_update_flag.clear()
                if self.in_service_menu and self.current_context:
                    time.sleep(0.5)
                    with self.input_lock:
                        try:
                            print("\r" + " " * 80 + "\r", end="")
                            print("\033[A" * 2, end="")
                            self.show_service_menu()
                            print(f"{self.current_input_prompt}", end="", flush=True)
                        except:
                            pass

    async def run(self):
        if not self.contexts and not self.context_statuses:
            print("❌ No contexts configured or discovered.")
            return

        print("\n🚀 KubeWire - Kubernetes Port Forward Manager")
        print("=" * 50)

        display_thread = threading.Thread(target=self._display_update_thread, daemon=True)
        display_thread.start()

        accessible_contexts = [ctx for ctx in self.contexts.keys()]
        if len(accessible_contexts) == 1:
            self.current_context = accessible_contexts[0]
            self.current_pods = self.contexts[self.current_context]
            print(f"🎯 Auto-selected context: {self.current_context}")
        else:
            await self.select_context()

        self.pod_monitor.start_monitoring()

        try:
            while self.running:
                if self.current_context:
                    self.in_service_menu = True
                    self.show_service_menu()

                    with self.input_lock:
                        self.current_input_prompt = "\nEnter your choice: "
                        print(self.current_input_prompt, end="", flush=True)

                        choice = self._get_user_input_with_refresh()

                    try:
                        await self.handle_service_choice(choice)
                    except KeyboardInterrupt:
                        print("\n👋 Shutting down...")
                        self.stop_all()
                        self.running = False
                    except Exception as e:
                        print(f"❌ Error: {e}")
                else:
                    self.in_service_menu = False
                    await self.select_context()
        finally:
            self.pod_monitor.stop_monitoring()

    def _get_user_input_with_refresh(self):
        self.refresh_requested.clear()

        input_result = [None]
        input_ready = threading.Event()

        def get_input():
            try:
                result = input().strip()
                input_result[0] = result
                input_ready.set()
            except (EOFError, KeyboardInterrupt):
                input_ready.set()

        input_thread = threading.Thread(target=get_input, daemon=True)
        input_thread.start()

        while True:
            if input_ready.wait(timeout=0.1):
                return input_result[0] if input_result[0] is not None else ""

            if self.refresh_requested.is_set():
                self.refresh_requested.clear()
                self.show_service_menu()
                print(self.current_input_prompt, end="", flush=True)

            if not input_thread.is_alive() and not input_ready.is_set():
                return ""

    async def select_context(self):
        self.pod_monitor.stop_monitoring()
        self.in_service_menu = False
        os.system('cls' if os.name == 'nt' else 'clear')

        print(f"\n🌍 Available Environments/Contexts:")
        print("-" * 40)

        accessible_contexts = list(self.contexts.keys())
        all_contexts = []

        for ctx in accessible_contexts:
            status = next((s for s in self.context_statuses if s.name == ctx), None)
            service_count = len(self.contexts[ctx]) if ctx in self.contexts else 0
            all_contexts.append({
                'name': ctx,
                'accessible': True,
                'service_count': service_count,
                'error': ''
            })

        for status in self.context_statuses:
            if not status.accessible:
                all_contexts.append({
                    'name': status.name,
                    'accessible': False,
                    'service_count': 0,
                    'error': status.error_message
                })

        for i, ctx_info in enumerate(all_contexts, 1):
            current_marker = "👉 " if ctx_info['name'] == self.current_context else "   "
            if ctx_info['accessible']:
                print(f"{current_marker}{i}. 🟢 {ctx_info['name']} ({ctx_info['service_count']} services)")
            else:
                print(f"{current_marker}{i}. 🔴 {ctx_info['name']} (⚠️  {ctx_info['error']})")

        print("\n🎮 Commands:")
        print("  1-N      : Select environment")
        if self.current_context:
            print("  back     : Back to current context")
        print("  refresh  : Refresh/Re-discover")
        print("  quit     : Quit")

        choice = input("\nSelect environment: ").strip().lower()

        if choice == 'q' or choice == 'quit':
            print("👋 Stopping all services and exiting...\n")
            self.stop_all_contexts()
            self.running = False
        elif choice == 'r' or choice == 'refresh':
            print("🔄 Re-discovering configuration...\n")
            new_contexts, new_statuses = ConfigManager.discover_config()
            self.contexts = new_contexts
            self.context_statuses = new_statuses
            self.current_context = None
            self.current_pods = []
            self.notified_disconnected_pods.clear()
            if new_contexts:
                ConfigManager.save_discovered_config(new_contexts)
                print("✅ Configuration refreshed!")
            else:
                print("⚠️  No accessible contexts found")
        elif choice == 'b' or choice == 'back':
            if self.current_context:
                self.pod_monitor.start_monitoring()
                os.system('cls' if os.name == 'nt' else 'clear')
                return
            else:
                print("❌ Invalid choice")
                await asyncio.sleep(1)
        elif choice.isdigit():
            index = int(choice) - 1
            if 0 <= index < len(all_contexts):
                selected_context = all_contexts[index]
                if not selected_context['accessible']:
                    print(f"❌ Cannot access context '{selected_context['name']}': {selected_context['error']}")
                    print("💡 Possible solutions:")
                    if "Authentication required" in selected_context['error']:
                        print("   - Authenticate with your cluster provider")
                        print("   - Update your kubeconfig file")
                        print("   - Check your cluster credentials")
                    elif "Connection timeout" in selected_context['error']:
                        print("   - Check your network connection")
                        print("   - Verify the cluster is running and accessible")
                    elif "Access denied" in selected_context['error']:
                        print("   - Check your cluster permissions")
                        print("   - Verify your kubectl configuration")
                    elif "Unknown error" in selected_context['error']:
                        print("   - Unknown")
                    await asyncio.sleep(3)
                    await self.select_context()
                    return
                new_context = selected_context['name']
                if new_context != self.current_context:
                    if self.current_context:
                        self.stop_current_context()
                    self.current_context = new_context
                    self.current_pods = self.contexts[new_context]
                    self.notified_disconnected_pods.clear()
                    for pod in self.current_pods:
                        pod._was_running = pod.is_running()
                    self.pod_monitor.start_monitoring()
                    await asyncio.sleep(1)
                    os.system('cls' if os.name == 'nt' else 'clear')
                else:
                    await asyncio.sleep(1)
            else:
                print("❌ Invalid environment number")
                await asyncio.sleep(1)
        else:
            print("❌ Invalid choice")
            await asyncio.sleep(1)

    def show_service_menu(self):
        os.system('cls' if os.name == 'nt' else 'clear')
        print(f"\n🎯 Context: {self.current_context}")

        print(f"📋 Available Services ({datetime.now().strftime('%H:%M:%S')}):")
        print("-" * 50)

        for i, pod in enumerate(self.current_pods, 1):
            pod_id = f"{pod.get_context()}/{pod.get_namespace()}/{pod.get_service()}"
            is_running = pod.is_running()
            is_starting = getattr(pod, "_is_starting", False)
            is_failed = self._is_pod_failed(pod)

            if is_starting:
                status_icon = "🟡"
                status_text = "STARTING"
            elif is_failed:
                status_icon = "💥"
                status_text = "FAILED"
                if self.sound_enabled and pod_id not in self.notified_disconnected_pods:
                    self.notified_disconnected_pods.add(pod_id)
                    threading.Thread(target=self.sound_notifier.play_disconnect_sound, daemon=True).start()
            elif is_running:
                status_icon = "🟢"
                status_text = "RUNNING"
                self.notified_disconnected_pods.discard(pod_id)
            else:
                status_icon = "🔴"
                status_text = "STOPPED"
                self.notified_disconnected_pods.discard(pod_id)

            print(f"{i:2d}. {pod.get_service()}:{pod.get_port()} [{pod.get_namespace()}] - {status_icon} {status_text}")

        print("\n🎮 Commands:")
        print("  1-N      : Start/Stop specific service")
        print("  l1-N     : Show logs for service (new window)")
        print("  start    : Start all services")
        print("  stop     : Stop all services")
        print("  env      : Change environment")
        print("  refresh  : Re-discover services")
        print("  quit     : Quit")

    async def handle_service_choice(self, choice: str):
        if choice is None:
            choice = ""

        choice = choice.lower().strip()

        if choice.startswith('l') and choice[1:].isdigit():
            index = int(choice[1:]) - 1
            if 0 <= index < len(self.current_pods):
                await self.show_pod_logs(self.current_pods[index])
                return

        if choice == 'q' or choice == 'quit':
            self._log_console("👋 Stopping all services and exiting...")
            self.stop_all_contexts()
            self.running = False
        elif choice == 'env' or choice == 'e':
            self._log_console("🔄 Switching to environment selection...")
            await asyncio.sleep(0.5)
            await self.select_context()
        elif choice == 'refresh' or choice == 'r':
            self._log_console("🔄 Re-discovering services...")
            new_contexts, new_statuses = ConfigManager.discover_config()
            if new_contexts:
                self.stop_current_context()
                self.contexts = new_contexts
                self.context_statuses = new_statuses
                self.notified_disconnected_pods.clear()
                if self.current_context in new_contexts:
                    self.current_pods = new_contexts[self.current_context]
                    for pod in self.current_pods:
                        pod._was_running = pod.is_running()
                    ConfigManager.save_discovered_config(new_contexts)
                    self._log_console(f"✅ Refreshed context: {self.current_context}")
                    self.show_service_menu()
                else:
                    self.current_context = None
                    self.current_pods = []
                    ConfigManager.save_discovered_config(new_contexts)
                    self._log_console("⚠️ Context no longer exists, please select a new one.")
                    await self.select_context()
            else:
                self._log_console("⚠️ No contexts found!")
            await asyncio.sleep(0.5)
        elif choice == 'start':
            stopped_pods = [pod for pod in self.current_pods if not pod.is_running()]
            if not stopped_pods:
                self._log_console("✅ All services are already running!")
                await asyncio.sleep(1)
                return

            total = len(stopped_pods)
            started_ok = 0
            for i, pod in enumerate(stopped_pods, 1):
                pod._is_starting = True
                from datetime import datetime
                timestamp = datetime.now().strftime("%H:%M:%S")
                msg = f"[{timestamp}] 🚀 Starting {i}/{total}: {pod.get_service()}..."
                print(f"\r{msg}{' ' * 40}", end="", flush=True)
                await asyncio.sleep(0.1)
                success = await pod.start()
                pod._is_starting = False
                pod_id = f"{pod.get_context()}/{pod.get_namespace()}/{pod.get_service()}"
                if success:
                    pod._was_running = True
                    self.pod_monitor.mark_user_started(pod_id)
                    self.notified_disconnected_pods.discard(pod_id)
                    started_ok += 1
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    result_msg = f"[{timestamp}] ✅ Started {pod.get_service()} successfully!"
                else:
                    pod._was_running = False
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    result_msg = f"[{timestamp}] ❌ Failed to start {pod.get_service()}!"
                print(f"\r{result_msg}{' ' * 40}", end="", flush=True)
                await asyncio.sleep(0.7)
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"\r[{timestamp}] 🚀 Start completed: {started_ok}/{total} services started successfully.{' ' * 40}")
            await asyncio.sleep(1)
        elif choice == 'stop':
            running_pods = [pod for pod in self.current_pods if pod.is_running()]
            total = len([pod for pod in self.current_pods])
            if not running_pods:
                from datetime import datetime
                timestamp = datetime.now().strftime("%H:%M:%S")
                print(f"\r[{timestamp}] 🛑 Stop completed: {total}/{total} services stopped successfully.{' ' * 40}")
                await asyncio.sleep(1)
                return

            total = len(running_pods)
            stopped_ok = 0
            for i, pod in enumerate(running_pods, 1):
                from datetime import datetime
                timestamp = datetime.now().strftime("%H:%M:%S")
                msg = f"[{timestamp}] 🛑 Stopping {i}/{total}: {pod.get_service()}..."
                print(f"\r{msg}{' ' * 40}", end="", flush=True)
                pod_id = f"{pod.get_context()}/{pod.get_namespace()}/{pod.get_service()}"
                success = pod.stop()
                if success:
                    pod._was_running = False
                    self.pod_monitor.mark_user_stopped(pod_id)
                    self.notified_disconnected_pods.discard(pod_id)
                    stopped_ok += 1
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    result_msg = f"[{timestamp}] ✅ Stopped {pod.get_service()} successfully!"
                else:
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    result_msg = f"[{timestamp}] ❌ Failed to stop {pod.get_service()}!"
                print(f"\r{result_msg}{' ' * 40}", end="", flush=True)
                await asyncio.sleep(0.7)
            self.stop_current_context()
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"\r[{timestamp}] 🛑 Stop completed: {stopped_ok}/{total} services stopped successfully.{' ' * 40}")
            await asyncio.sleep(1)
        elif choice.isdigit():
            index = int(choice) - 1
            if 0 <= index < len(self.current_pods):
                pod = self.current_pods[index]
                pod_id = f"{pod.get_context()}/{pod.get_namespace()}/{pod.get_service()}"
                service_name = pod.get_service()

                if pod.is_running():
                    from datetime import datetime
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    msg = f"[{timestamp}] 🛑 Stopping {service_name}..."
                    print(f"\r{msg}{' ' * 40}", end="", flush=True)
                    pod.stop()
                    pod._was_running = False
                    self.pod_monitor.mark_user_stopped(pod_id)
                    self.notified_disconnected_pods.discard(pod_id)
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    msg = f"[{timestamp}] ✅ Stopped {service_name} successfully!"
                    print(f"\r{msg}{' ' * 40}", end="", flush=True)
                    await asyncio.sleep(0.8)
                else:
                    pod._is_starting = True
                    from datetime import datetime
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    msg = f"[{timestamp}] 🚀 Starting {service_name}..."
                    print(f"\r{msg}{' ' * 40}", end="", flush=True)
                    success = await pod.start()
                    pod._is_starting = False
                    if success:
                        pod._was_running = True
                        self.pod_monitor.mark_user_started(pod_id)
                        self.notified_disconnected_pods.discard(pod_id)
                        timestamp = datetime.now().strftime("%H:%M:%S")
                        msg = f"[{timestamp}] ✅ Started {service_name} successfully!"
                    else:
                        pod._was_running = False
                        timestamp = datetime.now().strftime("%H:%M:%S")
                        msg = f"[{timestamp}] ❌ Failed to start {service_name}!"
                    print(f"\r{msg}{' ' * 40}", end="", flush=True)
                    await asyncio.sleep(0.8)
                await asyncio.sleep(0.8)
            else:
                self._log_console("❌ Invalid service number")
                await asyncio.sleep(1)
        elif choice == "":
            pass
        else:
            self._log_console("❌ Invalid choice")
            await asyncio.sleep(1)

    async def show_pod_logs(self, pod):
        context = pod.get_context()
        namespace = pod.get_namespace()
        service = pod.get_service()

        if self._is_stern_available():
            cmd = f"stern -n {namespace} -l app={service} --since 1h --color always"
            title = f"Logs: {service} (stern)"
        else:
            cmd = f"kubectl logs -n {namespace} -l app={service} --since=1h --tail=100 --follow"
            title = f"Logs: {service} (kubectl)"

        terminal_cmd = self._get_terminal_command(service, cmd, title)

        if terminal_cmd:
            try:
                subprocess.Popen(terminal_cmd, shell=True)
                from datetime import datetime
                timestamp = datetime.now().strftime("%H:%M:%S")
                print(f"[{timestamp}] 📜 Opening logs for {service} in new window...")
            except Exception as e:
                from datetime import datetime
                timestamp = datetime.now().strftime("%H:%M:%S")
                print(f"[{timestamp}] ❌ Failed to open logs: {e}")
        else:
            from datetime import datetime
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] ⚠️  Could not determine how to open new terminal window")

        await asyncio.sleep(1)

    def _is_stern_available(self) -> bool:
        try:
            subprocess.run(["stern", "--version"],
                           check=True,
                           stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
            return True
        except:
            return False

    def _get_terminal_command(self, service: str, cmd: str, title: str) -> str:
        escaped_cmd = cmd.replace('"', '\\"')
        escaped_title = title.replace('"', '\\"')

        if sys.platform == "win32":
            return f'''start wt -w 0 new-tab --title "Logs: {service}" powershell -NoExit -Command "{escaped_cmd}"'''

        elif sys.platform == "darwin":
            terminal_apps = []
            for app in ["Warp", "iTerm", "Terminal"]:
                if os.path.exists(f"/Applications/{app}.app"):
                    terminal_apps.append(app)

            if not terminal_apps:
                print("❌ No se encontró ninguna aplicación de terminal instalada")
                return ""

            if "Warp" in terminal_apps:
                return f"""
    osascript -e 'tell application "Warp" to activate'
    osascript -e 'delay 1'
    osascript -e 'tell application "System Events" to tell process "Warp"
        keystroke "n" using command down
        delay 0.5
        keystroke "{escaped_cmd}"
        key code 36
        keystroke "f" using {{command down, control down}}
    end tell'
    """
            elif "iTerm" in terminal_apps:
                return f"""
    osascript -e 'tell application "iTerm"
        activate
        set newWindow to (create window with default profile)
        tell current session of newWindow
            write text "{escaped_cmd}"
            set name to "{escaped_title}"
        end tell
        set fullscreen of newWindow to true
    end tell'
    """
            else:
                return f"""
    osascript -e 'tell application "Terminal"
        activate
        do script "{escaped_cmd}"
        delay 1
    end tell'
    osascript -e 'tell application "System Events" to tell process "Terminal"
        set frontmost to true
        keystroke "f" using {{command down, control down}}
    end tell'
    """
        else:
            return f"""
    bash -c '
    if command -v warp &>/dev/null; then
        warp --title "{escaped_title}" --command "{escaped_cmd}" --fullscreen &
    elif command -v gnome-terminal &>/dev/null; then
        gnome-terminal --title="{escaped_title}" -- bash -c "{escaped_cmd}; exec bash" &
        sleep 0.5
        wmctrl -r "{escaped_title}" -b add,maximized_vert,maximized_horz
    elif command -v konsole &>/dev/null; then
        konsole --title "{escaped_title}" --fullscreen -e bash -c "{escaped_cmd}; exec bash" &
    elif command -v xterm &>/dev/null; then
        xterm -title "{escaped_title}" -geometry 132x45 -e "{escaped_cmd}" &
    else
        echo "No se encontró ningún terminal compatible" >&2
    fi
    '
    """

    def clear_line(self):
        print("\r" + " " * 100 + "\r", end="")

    def stop_current_context(self):
        if not self.current_pods:
            return
        for pod in self.current_pods:
            if pod.is_running():
                pod.stop()
                pod._was_running = False

    def stop_all_contexts(self):
        for context_name, pods in self.contexts.items():
            for pod in pods:
                if pod.is_running():
                    pod.stop()
                    pod._was_running = False

    def stop_all(self):
        self.stop_all_contexts()

    def notify_failures(self, failed_pods):
        """Método llamado por el monitor cuando detecta fallos"""
        if self.sound_enabled and failed_pods:
            new_failures = []
            for pod_id in failed_pods:
                if pod_id not in self.notified_disconnected_pods:
                    new_failures.append(pod_id)
                    self.notified_disconnected_pods.add(pod_id)

            if new_failures:
                threading.Thread(target=self.sound_notifier.play_disconnect_sound, daemon=True).start()

    def trigger_refresh_with_failures(self, failed_pods):
        """Método llamado por el monitor para refrescar la pantalla con fallos"""
        if failed_pods:
            self.notify_failures(failed_pods)
        self.trigger_display_update()

    def _is_pod_failed(self, pod):
        pod_id = f"{pod.get_context()}/{pod.get_namespace()}/{pod.get_service()}"
        previously_running = getattr(pod, "_was_running", False)
        currently_running = pod.is_running()
        starting = getattr(pod, "_is_starting", False)
        if starting:
            return False
        recently_failed = False
        if hasattr(self.pod_monitor, "recently_failed_pods"):
            recently_failed = pod_id in self.pod_monitor.recently_failed_pods
        return (previously_running and (recently_failed or not currently_running))