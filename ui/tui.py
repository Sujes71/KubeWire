from datetime import datetime
import asyncio

from config.config_manager import ConfigManager
from models.models import ContextStatus
from pods.pod_ui import PodUI

class TUI:
    def __init__(self, contexts, context_statuses=None):
        self.contexts = contexts
        self.context_statuses = context_statuses or []
        self.current_context = None
        self.current_pods = []
        self.running = True

    async def run(self):
        if not self.contexts and not self.context_statuses:
            print("❌ No contexts configured or discovered.")
            return

        print("🚀 KubeWire - Kubernetes Port Forward Manager")
        print("=" * 50)

        accessible_contexts = [ctx for ctx in self.contexts.keys()]
        if len(accessible_contexts) == 1:
            self.current_context = accessible_contexts[0]
            self.current_pods = self.contexts[self.current_context]
            print(f"🎯 Auto-selected context: {self.current_context}")
        else:
            await self.select_context()

        while self.running:
            if self.current_context:
                self.show_service_menu()
                choice = input("\nEnter your choice: ").strip()
                try:
                    await self.handle_service_choice(choice)
                except KeyboardInterrupt:
                    print("\n👋 Shutting down...")
                    self.stop_all()
                    self.running = False
                except Exception as e:
                    print(f"❌ Error: {e}")
            else:
                await self.select_context()

    async def select_context(self):
        print(f"🌍 Available Environments/Contexts:")
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
        print("  1-N : Select environment")
        if self.current_context:
            print("  b   : Back to current context")
        print("  r   : Refresh/Re-discover")
        print("  q   : Quit")

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
                print("✅ Configuration refreshed!\n")
            else:
                print("⚠️  No accessible contexts found\n")
        elif choice == 'b':
            if self.current_context:
                print("🔄 Returning to current context...")
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
                    await asyncio.sleep(3)
                    return
                new_context = selected_context['name']
                if new_context != self.current_context:
                    if self.current_context:
                        self.stop_current_context()
                    self.current_context = new_context
                    self.current_pods = self.contexts[new_context]
                    print(f"🎯 Switched to context: {self.current_context}")
                    await asyncio.sleep(1)
                else:
                    print(f"📍 Already in context: {self.current_context}")
                    await asyncio.sleep(1)
            else:
                print("❌ Invalid environment number")
                await asyncio.sleep(1)
        else:
            print("❌ Invalid choice")
            await asyncio.sleep(1)

    def show_service_menu(self):
        print(f"\n🎯 Context: {self.current_context}")
        print(f"📋 Available Services ({datetime.now().strftime('%H:%M:%S')}):")
        print("-" * 50)
        for i, pod in enumerate(self.current_pods, 1):
            status = "🟢 RUNNING" if pod.is_running() else "🔴 STOPPED"
            print(f"{i:2d}. {pod.get_service()}:{pod.get_port()} [{pod.get_namespace()}] - {status}")
        print("\n🎮 Commands:")
        print("  1-N      : Start/Stop specific service")
        print("  start    : Start all services")
        print("  stop     : Stop all services")
        print("  env      : Change environment")
        print("  refresh  : Re-discover services")
        print("  q        : Quit")

    async def handle_service_choice(self, choice: str):
        choice = choice.lower().strip()
        if choice == 'q' or choice == 'quit':
            print("👋 Stopping all services and exiting...\n")
            self.stop_all_contexts()
            self.running = False
        elif choice == 'env':
            await self.select_context()
        elif choice == 'refresh':
            print("🔄 Re-discovering services...\n")
            new_contexts, new_statuses = ConfigManager.discover_config()
            if new_contexts:
                self.stop_current_context()
                self.contexts = new_contexts
                self.context_statuses = new_statuses
                if self.current_context in new_contexts:
                    self.current_pods = new_contexts[self.current_context]
                else:
                    self.current_context = None
                    self.current_pods = []
                ConfigManager.save_discovered_config(new_contexts)
                print("✅ Services refreshed!")
            else:
                print("❌ No accessible contexts found\n")
        elif choice == 'start':
            print(f"🚀 Starting all services in {self.current_context}...\n")
            success_count = 0
            total_count = 0
            for pod in self.current_pods:
                if not pod.is_running():
                    total_count += 1
                    if await pod.start():
                        success_count += 1
            print(f"📊 Summary: {success_count}/{total_count} services started successfully")
        elif choice == 'stop':
            print(f"🛑 Stopping all services in {self.current_context}...\n")
            self.stop_current_context()
        elif choice.isdigit():
            index = int(choice) - 1
            if 0 <= index < len(self.current_pods):
                pod = self.current_pods[index]
                if pod.is_running():
                    pod.stop()
                else:
                    await pod.start()
            else:
                print("❌ Invalid service number")
        else:
            print("❌ Invalid choice")
        if choice != 'status':
            await asyncio.sleep(0.5)

    def stop_current_context(self):
        if not self.current_pods:
            return
        for pod in self.current_pods:
            if pod.is_running():
                pod.stop()

    def stop_all_contexts(self):
        for context_name, pods in self.contexts.items():
            for pod in pods:
                if pod.is_running():
                    pod.stop()

    def stop_all(self):
        self.stop_all_contexts()
