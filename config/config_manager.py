from pathlib import Path
import yaml
import os
from typing import Tuple, Dict, List

from pods import Pod, PodUI
from models.models import ContextStatus
from k8s.discovery import KubernetesDiscovery

class ConfigManager:
    @staticmethod
    def get_config_path() -> Path:
        env_var = "KubeWire_CONFIG"
        if env_var in os.environ:
            return Path(os.environ[env_var]) / "config.yml"
        else:
            script_dir = Path(__file__).parent
            return script_dir / "config.yml"

    @staticmethod
    def discover_config() -> Tuple[Dict[str, List[PodUI]], List[ContextStatus]]:
        print("🔧 Auto-discovering Kubernetes configuration...")
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
                print(f"   ✅ Added {len(context_pods)} services from context {context}")
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
            with open(config_file, 'w') as f:
                yaml.dump(config_data, f, default_flow_style=False, sort_keys=False)
            print(f"\n💾 Configuration saved to {config_file}")
        except Exception as e:
            print(f"❌ Failed to save configuration: {e}")

    @staticmethod
    def read_config() -> Dict[str, List[PodUI]]:
        config_file = ConfigManager.get_config_path()
        if not config_file.exists():
            print(f"📝 No configuration file found at {config_file}")
            return {}

        print(f"Reading configuration from {config_file}")
        try:
            with open(config_file, 'r') as f:
                content = f.read().strip()
                if not content:
                    return {}

                config_data = yaml.safe_load(content)
                if not config_data or 'contexts' not in config_data:
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
                    result[context_name] = context_pods  # ✅ Siempre asigna aunque esté vacío

                return result  # ✅ Añade este return explícito

        except Exception as e:
            print(f"❌ Error reading config file: {e}")
            return {}
