import os
import sys
from pathlib import Path
from typing import Tuple, Dict, List

import yaml

from k8s.discovery import KubernetesDiscovery
from models.models import ContextStatus
from pods import Pod, PodUI


class ConfigManager:
    @staticmethod
    def get_config_path() -> Path:
        env_var = "KubeWire_CONFIG"
        if env_var in os.environ:
            return Path(os.environ[env_var]) / "config.yml"

        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            if sys.platform == "win32":
                config_dir = Path.home() / "AppData" / "Local" / "KubeWire"
            elif sys.platform == "darwin":
                config_dir = Path.home() / "Library" / "Application Support" / "KubeWire"
            else:
                config_dir = Path.home() / ".config" / "KubeWire"

            config_dir.mkdir(parents=True, exist_ok=True)
            return config_dir / "config.yml"
        else:
            script_dir = Path(__file__).parent
            config_dir = script_dir / "config"
            config_dir.mkdir(parents=True, exist_ok=True)
            return config_dir / "config.yml"

    @staticmethod
    def get_resource_path(relative_path: str) -> Path:
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            return Path(sys._MEIPASS) / relative_path
        else:
            return Path(__file__).parent / relative_path

    @staticmethod
    def discover_config() -> Tuple[Dict[str, List[PodUI]], List[ContextStatus]]:
        contexts = KubernetesDiscovery.get_contexts()
        if not contexts:
            print("❌ No contexts found")
            return {}, []

        result = {}
        context_statuses = []

        for context in contexts:
            print(f"\n🎯 Processing context: {context}")
            accessible, error_msg = KubernetesDiscovery.check_context_access(context)
            if not accessible:
                print(f"   ❌ Context {context} is not accessible: {error_msg}")
                context_statuses.append(ContextStatus(name=context, accessible=False, error_message=error_msg, service_count=0))
                continue

            context_pods = []
            namespaces = KubernetesDiscovery.get_namespaces(context)

            port_counter = 8080
            for namespace in namespaces:
                if namespace in ['kube-system', 'kube-public', 'kube-node-lease', 'default']:
                    continue
                services = KubernetesDiscovery.get_services(context, namespace)
                for service in services:
                    pod = Pod(context=context, namespace=namespace, service=service['name'], port=port_counter)
                    context_pods.append(PodUI(pod))
                    port_counter += 1

            context_statuses.append(ContextStatus(name=context, accessible=True, error_message="", service_count=len(context_pods)))

            if context_pods:
                result[context] = context_pods
                from datetime import datetime
                timestamp = datetime.now().strftime("%H:%M:%S")
                print(f"[{timestamp}] ✅ Added {len(context_pods)} services from context {context}")
            else:
                print(f"   ⚠️  No services found in context {context}")

        return result, context_statuses

    @staticmethod
    def save_discovered_config(contexts: Dict[str, List[PodUI]]):
        config_file = ConfigManager.get_config_path()
        config_data = { 'contexts': [] }

        for context_name, pods in contexts.items():
            context_config = { 'context': context_name, 'namespaces': [] }
            namespace_groups = {}
            for pod in pods:
                ns = pod.get_namespace()
                if ns not in namespace_groups:
                    namespace_groups[ns] = []
                namespace_groups[ns].append(pod)

            for ns_name, ns_pods in namespace_groups.items():
                namespace_config = { 'namespace': ns_name, 'pods': [] }
                for pod in ns_pods:
                    namespace_config['pods'].append({ 'service': pod.get_service(), 'port': pod.get_port() })
                context_config['namespaces'].append(namespace_config)

            config_data['contexts'].append(context_config)

        try:
            config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(config_file, 'w', encoding='utf-8') as f:
                yaml.dump(config_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            from datetime import datetime
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] 💾 Configuration saved to {config_file}")
        except Exception as e:
            from datetime import datetime
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] ❌ Failed to save configuration: {e}")

    @staticmethod
    def read_config() -> Dict[str, List[PodUI]]:
        config_file = ConfigManager.get_config_path()

        # Mostrar información de debug
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] 🔍 Looking for config file at: {config_file}")
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] 🔍 Config file exists: {config_file.exists()}")

        if not config_file.exists():
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] ⚠️  Config file not found. Will be created after first discovery.")
            return {}

        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    print(f"[{timestamp}] ⚠️  Config file is empty.")
                    return {}

                config_data = yaml.safe_load(content)
                if not config_data or 'contexts' not in config_data:
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    print(f"[{timestamp}] ⚠️  Config file has invalid format.")
                    return {}

                result = {}

                for context_data in config_data['contexts']:
                    context_name = context_data['context']
                    context_pods = []
                    for namespace_data in context_data.get('namespaces', []):
                        namespace_name = namespace_data['namespace']
                        for pod_data in namespace_data.get('pods', []):
                            pod = Pod(
                                context=context_name,
                                namespace=namespace_name,
                                service=pod_data['service'],
                                port=pod_data['port']
                            )
                            context_pods.append(PodUI(pod))
                    result[context_name] = context_pods

                timestamp = datetime.now().strftime("%H:%M:%S")
                print(f"[{timestamp}] ✅ Loaded configuration with {len(result)} contexts")
                return result

        except Exception as e:
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] ❌ Error reading config file: {e}")
            return {}

    @staticmethod
    def get_config_info():
        config_path = ConfigManager.get_config_path()
        is_frozen = getattr(sys, 'frozen', False)

        info = {
            'is_frozen': is_frozen,
            'config_path': str(config_path),
            'config_exists': config_path.exists(),
            'platform': sys.platform
        }

        if is_frozen:
            info['meipass'] = getattr(sys, '_MEIPASS', 'Not available')

        return info