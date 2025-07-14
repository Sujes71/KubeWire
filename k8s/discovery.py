import json
import subprocess
from typing import List, Dict, Tuple

class KubernetesDiscovery:
    @staticmethod
    def run_kubectl_command(cmd: List[str]) -> Tuple[bool, str]:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return True, result.stdout.strip()
        except subprocess.CalledProcessError as e:
            return False, e.stderr.strip()
        except FileNotFoundError:
            return False, "kubectl command not found"

    @staticmethod
    def get_contexts() -> List[str]:
        print("🔍 Discovering Kubernetes contexts...")
        success, output = KubernetesDiscovery.run_kubectl_command([
            "kubectl", "config", "get-contexts", "-o", "name"
        ])
        if success:
            contexts = [ctx.strip() for ctx in output.split('\n') if ctx.strip()]
            print(f"   Found {len(contexts)} contexts")
            return contexts
        else:
            print(f"   ❌ Failed to get contexts: {output}")
            return []

    @staticmethod
    def check_context_access(context: str) -> Tuple[bool, str]:
        success, output = KubernetesDiscovery.run_kubectl_command([
            "kubectl", "get", "namespaces", "--context", context, "-o", "name", "--request-timeout=5s"
        ])
        if success:
            return True, ""
        else:
            output_lower = output.lower()
            if "provide credentials" in output_lower or "logged in" in output_lower:
                return False, "Authentication required"
            elif "timeout" in output_lower or "connection refused" in output_lower:
                return False, "Connection timeout"
            elif "forbidden" in output_lower or "unauthorized" in output_lower:
                return False, "Access denied"
            elif "not found" in output_lower:
                return False, "Context not found"
            else:
                return False, "Unknown error"

    @staticmethod
    def get_namespaces(context: str) -> List[str]:
        print(f"🔍 Discovering namespaces in context: {context}")
        success, output = KubernetesDiscovery.run_kubectl_command([
            "kubectl", "get", "namespaces", "--context", context, "-o", "name"
        ])
        if success:
            namespaces = []
            for line in output.split('\n'):
                if line.strip().startswith('namespace/'):
                    ns = line.strip().replace('namespace/', '')
                    namespaces.append(ns)
            print(f"   Found {len(namespaces)} namespaces")
            return namespaces
        else:
            if "provide credentials" in output.lower() or "logged in" in output.lower():
                print(f"   ❌ Authentication required for context: {context}")
            else:
                print(f"   ❌ Failed to get namespaces: {output}")
            return []

    @staticmethod
    def get_services(context: str, namespace: str) -> List[Dict[str, any]]:
        print(f"🔍 Discovering services in {context}/{namespace}")
        success, output = KubernetesDiscovery.run_kubectl_command([
            "kubectl", "get", "services", "--context", context, "--namespace", namespace, "-o", "json"
        ])
        if success:
            try:
                services_data = json.loads(output)
                services = []
                for item in services_data.get('items', []):
                    service_name = item.get('metadata', {}).get('name', '')
                    service_spec = item.get('spec', {})
                    ports = service_spec.get('ports', [])
                    if service_name == 'kubernetes' or not ports:
                        continue
                    first_port = ports[0].get('port', 80)
                    services.append({
                        'name': service_name,
                        'port': first_port,
                        'all_ports': [p.get('port') for p in ports]
                    })
                print(f"   Found {len(services)} services")
                return services
            except json.JSONDecodeError as e:
                print(f"   ❌ Failed to parse services JSON: {e}")
                return []
        else:
            if "provide credentials" in output.lower() or "logged in" in output.lower():
                print(f"   ❌ Authentication required for context: {context}")
            else:
                print(f"   ❌ Failed to get services: {output}")
            return []
