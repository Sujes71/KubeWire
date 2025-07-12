# ⚡ Kubewire

![Kubewire Logo](logo.png)

> Terminal-based port-forwarding for Kubernetes services.  
> Auto-discovers clusters, namespaces, and services via `kubectl`.  
> Fast tunnels. Clean interface. Zero config.

---

## 🚀 Features

- 🔍 Context, namespace & service discovery powered by `kubectl`
- 🚪 Start/Stop port-forwarding from an interactive terminal UI
- 🎯 Multi-cluster awareness with status indicators
- 💾 Automatic `config.yml` generation (or manual override)
- 💥 Gracefully handles errors: endpoints, ports & authentication

---

## 📦 Installation

```bash
git clone https://github.com/zedven/kubewire.git
cd kubewire
python3 -m venv .venv
source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows
pip install -r requirements.txt
python -m core.main
