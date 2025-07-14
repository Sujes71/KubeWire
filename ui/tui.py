import asyncio
import os
import threading
import time
from datetime import datetime

from config.config_manager import ConfigManager
from pods.pod_monitor import PodMonitor


class TUI:
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

        for context_pods in self.contexts.values():
            for pod in context_pods:
                pod._was_running = False

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
                    return
                new_context = selected_context['name']
                if new_context != self.current_context:
                    if self.current_context:
                        self.stop_current_context()
                    self.current_context = new_context
                    self.current_pods = self.contexts[new_context]
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
            is_failed = pod_id in self.pod_monitor.recently_failed_pods

            if is_failed:
                status_icon = "💥"
                status_text = "DISCONNECTED"
            elif is_running:
                status_icon = "🟢"
                status_text = "RUNNING"
            else:
                status_icon = "🔴"
                status_text = "STOPPED"

            print(f"{i:2d}. {pod.get_service()}:{pod.get_port()} [{pod.get_namespace()}] - {status_icon} {status_text}")

        print("\n🎮 Commands:")
        print("  1-N      : Start/Stop specific service")
        print("  start    : Start all services")
        print("  stop     : Stop all services")
        print("  env      : Change environment")
        print("  refresh  : Re-discover services")
        print("  quit     : Quit")

    async def handle_service_choice(self, choice: str):
        if choice is None:
            choice = ""

        choice = choice.lower().strip()

        if choice == 'q' or choice == 'quit':
            print("👋 Stopping all services and exiting...\n")
            self.stop_all_contexts()
            self.running = False
        elif choice == 'env' or choice == 'e':
            print("🔄 Switching to environment selection...")
            await asyncio.sleep(0.5)
            await self.select_context()
        elif choice == 'refresh' or choice == 'r':
            print("🔄 Re-discovering services...", end="", flush=True)
            new_contexts, new_statuses = ConfigManager.discover_config()
            if new_contexts:
                self.stop_current_context()
                self.contexts = new_contexts
                self.context_statuses = new_statuses
                if self.current_context in new_contexts:
                    self.current_pods = new_contexts[self.current_context]
                    for pod in self.current_pods:
                        pod._was_running = pod.is_running()
                else:
                    self.current_context = None
                    self.current_pods = []
                ConfigManager.save_discovered_config(new_contexts)
                print(" ✅ Done!")
            else:
                print(" ⚠️ No contexts found!")
            await asyncio.sleep(0.5)
        elif choice == 'start':
            stopped_pods = [pod for pod in self.current_pods if not pod.is_running()]
            if not stopped_pods:
                print("✅ All services are already running!")
                await asyncio.sleep(1)
                return

            print(f"🚀 Starting {len(stopped_pods)} service(s)...", end="", flush=True)

            for i, pod in enumerate(stopped_pods, 1):
                print(f"\r🚀 Starting {i}/{len(stopped_pods)}: {pod.get_service()}...", end="", flush=True)
                await pod.start()
                pod._was_running = True
                pod_id = f"{pod.get_context()}/{pod.get_namespace()}/{pod.get_service()}"
                self.pod_monitor.mark_user_started(pod_id)
                await asyncio.sleep(0.1)

            print(f"\r✅ Started {len(stopped_pods)} service(s) successfully!{' '*20}")
            await asyncio.sleep(1)
        elif choice == 'stop':
            running_pods = [pod for pod in self.current_pods if pod.is_running()]
            if not running_pods:
                print("✅ All services are already stopped!")
                await asyncio.sleep(1)
                return

            print(f"🛑 Stopping {len(running_pods)} service(s)...", end="", flush=True)

            for i, pod in enumerate(running_pods, 1):
                print(f"\r🛑 Stopping {i}/{len(running_pods)}: {pod.get_service()}...", end="", flush=True)
                pod_id = f"{pod.get_context()}/{pod.get_namespace()}/{pod.get_service()}"
                self.pod_monitor.mark_user_stopped(pod_id)
                await asyncio.sleep(0.1)

            self.stop_current_context()
            print(f"\r✅ Stopped {len(running_pods)} service(s) successfully!{' '*20}")
            await asyncio.sleep(1)
        elif choice.isdigit():
            index = int(choice) - 1
            if 0 <= index < len(self.current_pods):
                pod = self.current_pods[index]
                pod_id = f"{pod.get_context()}/{pod.get_namespace()}/{pod.get_service()}"
                service_name = pod.get_service()

                if pod.is_running():
                    print(f"🛑 Stopping {service_name}...", end="", flush=True)
                    pod.stop()
                    pod._was_running = False
                    self.pod_monitor.mark_user_stopped(pod_id)
                    print(f"\r✅ Stopped {service_name} successfully!{' '*20}")
                else:
                    print(f"🚀 Starting {service_name}...", end="", flush=True)
                    if await pod.start():
                        pod._was_running = True
                        self.pod_monitor.mark_user_started(pod_id)
                        print(f"\r✅ Started {service_name} successfully!{' '*20}")
                    else:
                        print(f"\r❌ Failed to start {service_name}!{' '*20}")
                await asyncio.sleep(0.8)
            else:
                print("❌ Invalid service number")
                await asyncio.sleep(1)
        elif choice == "":
            pass
        else:
            print("❌ Invalid choice")
            await asyncio.sleep(1)

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
        pass

    def trigger_refresh_with_failures(self, failed_pods):
        pass