import asyncio
import sys

from config.config_manager import ConfigManager
from ui.tui import KubeWireTUI

MODE = "gui"

def _create_gui():
    from ui.gui import KubeWireGUI
    return KubeWireGUI()

async def _create_tui():
    try:
        contexts = ConfigManager.read_config()
        context_statuses = []

        if not contexts:
            contexts, context_statuses = ConfigManager.discover_config()
            if contexts:
                ConfigManager.save_discovered_config(contexts)

        accessible_count = len(contexts)
        inaccessible_count = len([s for s in context_statuses if not s.accessible])

        if accessible_count > 0:
            print(f"✅ Found {accessible_count} accessible context(s)")
        if inaccessible_count > 0:
            print(f"⚠️  Found {inaccessible_count} inaccessible context(s)")
        if accessible_count == 0:
            print("❌ No accessible contexts found.")
            print("💡 Possible solutions:")
            print("   1. Check your kubectl configuration: kubectl config get-contexts")
            print("   2. Authenticate with your cluster provider and update kubeconfig")
            print("   3. Verify your cluster credentials and permissions")
            print("   4. Create a manual config.yml file with your services")
            return

        tui = KubeWireTUI(contexts, context_statuses)
        await tui.run()

    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        print(f"❌ Fatal error in TUI: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main():
    if MODE.lower() == "tui":
        try:
            app = _create_gui()
            app.run()
        except KeyboardInterrupt:
            print("🛑 Application interrupted by the user")
        except Exception as e:
            print(f"❌ Fatal error in GUI: {e}")
            import traceback
            traceback.print_exc()
        finally:
            print("👋 KubeWire finished")
    else:
        asyncio.run(_create_tui())


if __name__ == "__main__":
    main()
