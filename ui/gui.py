import os
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox

from config.config_manager import ConfigManager
from pods.pod_monitor import PodMonitor
from pods.sound_notifier import SoundNotifier

SOLARIZED = {
    'base03': '#002b36',
    'base02': '#073642',
    'base01': '#586e75',
    'base00': '#657b83',
    'base0':  '#839496',
    'base1':  '#93a1a1',
    'base2':  '#eee8d5',
    'base3':  '#fdf6e3',
    'yellow': '#b58900',
    'orange': '#cb4b16',
    'red':    '#dc322f',
    'magenta':'#d33682',
    'violet': '#6c71c4',
    'blue':   '#268bd2',
    'cyan':   '#2aa198',
    'green':  '#859900',
}


class KubeWireGUI:
    def __init__(self):
        self.status_label = None
        self.logs_frame = None
        self.toggle_logs_button = None
        self._stream_pod_logs_to_gui = None
        self._spinner_running = None
        self._spinner_label = None
        self.context_combobox = None
        self.context_var = None
        self._loading_overlay = None
        self._last_states = None
        self.logs_text = None
        self.main_frame = None
        self.services_tree = None
        self.root = tk.Tk()
        self.root.title("🚀 KubeWire - Kubernetes Port Forward Manager")
        self.root.state('zoomed')
        self.root.lift()
        self.root.focus_force()
        self.root.attributes('-topmost', True)
        self.root.after(10, lambda: self.root.attributes('-topmost', False))


        try:
            root_dir = os.path.dirname(os.path.dirname(__file__))
            icon_path = os.path.join(root_dir, "icon.png")
            icon_img = tk.PhotoImage(file=icon_path)
            self.root.iconphoto(True, icon_img)
        except Exception as e:
            print(f"⚠️ No se pudo cargar el icono: {e}")

        self.contexts = {}
        self.context_statuses = []
        self.current_context = None
        self.current_pods = []
        self.running = True
        self.pod_monitor = None
        self.sound_notifier = SoundNotifier()
        self.sound_enabled = True
        self.notified_disconnected_pods = set()
        self.refresh_timer = None
        self.sort_column = None
        self.sort_reverse = False
        self.original_order = []
        self.window_has_focus = True
        self._service_to_item = {}

        self.current_selection = None

        self._initial_focus_done = False

        self.setup_styles()

        self.create_widgets()

        self.create_logs_frame()

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.initialize_app()

    def create_logs_frame(self):
        self.logs_frame = ttk.LabelFrame(self.main_frame, text="📜 Logs", padding="5")

        self.logs_text = tk.Text(self.logs_frame, height=15, wrap=tk.WORD,
                                 bg=SOLARIZED['base02'], fg=SOLARIZED['base0'], insertbackground=SOLARIZED['base0'])
        self.logs_text.pack(fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(self.logs_frame, command=self.logs_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.logs_text.configure(yscrollcommand=scrollbar.set)

    def toggle_logs_panel(self):
        if self.logs_frame.winfo_ismapped():
            self.logs_frame.grid_remove()
            self.main_frame.rowconfigure(3, weight=0)
            self.toggle_logs_button.config(text="🔼 Show logs")
        else:
            self.logs_frame.grid(row=3, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=10, pady=(5, 0))
            self.main_frame.rowconfigure(3, weight=1)
            self.toggle_logs_button.config(text="🔽 Hide logs")

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')

        self.root.configure(bg=SOLARIZED['base03'])

        style.configure('.',
                        background=SOLARIZED['base03'],
                        foreground=SOLARIZED['base0'],
                        fieldbackground=SOLARIZED['base02'],
                        relief='flat',
                        font=('Arial', 12))

        style.configure('Title.TLabel', font=('Arial', 16, 'bold'),
                        background=SOLARIZED['base03'], foreground=SOLARIZED['blue'])
        style.configure('Subtitle.TLabel', font=('Arial', 12, 'bold'),
                        background=SOLARIZED['base03'], foreground=SOLARIZED['base1'])
        style.configure('Status.TLabel', font=('Arial', 10),
                        background=SOLARIZED['base03'], foreground=SOLARIZED['base0'])

        style.configure('Running.TLabel', foreground=SOLARIZED['green'])
        style.configure('Stopped.TLabel', foreground=SOLARIZED['red'])
        style.configure('Failed.TLabel', foreground=SOLARIZED['orange'])

        # Mejorar Treeview: fuente más grande, centrado, colores y selección
        style.configure('Treeview',
                        background=SOLARIZED['base02'],
                        foreground=SOLARIZED['base0'],
                        fieldbackground=SOLARIZED['base02'],
                        rowheight=28,
                        bordercolor=SOLARIZED['base01'],
                        borderwidth=0,
                        font=('Arial', 13, 'bold'))
        style.map('Treeview',
                  background=[('selected', SOLARIZED['blue'])],
                  foreground=[('selected', SOLARIZED['base3'])])

        style.configure('Treeview.Heading',
                        background=SOLARIZED['base01'],
                        foreground=SOLARIZED['yellow'],
                        relief='raised',
                        font=('Arial', 14, 'bold'),
                        anchor='center')
        style.map('Treeview.Heading',
                  background=[('active', SOLARIZED['base00'])])

        style.configure('TLabelframe', background=SOLARIZED['base03'], foreground=SOLARIZED['base0'])
        style.configure('TLabelframe.Label', background=SOLARIZED['base03'], foreground=SOLARIZED['yellow'])

        style.configure('TButton', background=SOLARIZED['base02'], foreground=SOLARIZED['base0'])
        style.map('TButton',
                  background=[('active', SOLARIZED['base00'])],
                  foreground=[('disabled', SOLARIZED['base01'])])

        style.configure('TCombobox', fieldbackground=SOLARIZED['base02'], foreground=SOLARIZED['base0'])

    def create_widgets(self):
        self.main_frame = ttk.Frame(self.root, padding="10")
        self.main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.main_frame.columnconfigure(0, weight=1)
        self.main_frame.rowconfigure(1, weight=1)

        self.root.bind('<FocusIn>', self.on_window_focus_in)
        self.root.bind('<FocusOut>', self.on_window_focus_out)
        self.root.bind('<Button-1>', self.on_click_outside)
        self.root.bind_all('<Command-q>', lambda e: self.on_closing())
        self.root.bind_all('<Command-w>', lambda e: self.on_closing())
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        title_label = ttk.Label(
            self.main_frame,
            text="🚀 KubeWire",
            font=('Arial', 28, 'bold'),
            foreground=SOLARIZED['blue'],
            background=SOLARIZED['base03']
        )
        title_label.grid(row=0, column=0, pady=(0, 20))
        self.main_frame.columnconfigure(0, weight=1)

        self.create_services_frame()

        self.create_status_bar()

    def on_window_focus_in(self, event):
        if event.widget == self.root:
            self.window_has_focus = True
            if self.services_tree.get_children():
                self.root.after(50, self._ensure_focus_and_selection)

    def on_window_focus_out(self, event):
        if event.widget == self.root:
            self.window_has_focus = False

    def on_click_outside(self, event):
        if event.widget == self.services_tree:
            return
        widget_class = event.widget.__class__.__name__
        if widget_class in ['Button', 'TButton', 'Combobox', 'TCombobox', 'Scrollbar', 'Text', 'ScrolledText']:
            self.root.after(100, self._ensure_focus_and_selection)
            return
        if self.services_tree.get_children():
            self.root.after_idle(self._ensure_focus_and_selection)

    def create_services_frame(self):
        services_frame = ttk.Frame(self.main_frame, padding="10")
        services_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        services_frame.rowconfigure(1, weight=1)
        services_frame.columnconfigure(0, weight=1)

        context_control_frame = ttk.Frame(services_frame)
        context_control_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        context_control_frame.columnconfigure(1, weight=1)

        ttk.Label(context_control_frame, text="🌍 Context", style='Subtitle.TLabel').grid(row=0, column=0, padx=(0, 10))

        self.context_var = tk.StringVar()
        self.context_combobox = ttk.Combobox(context_control_frame, textvariable=self.context_var,
                                             state="readonly", width=40)
        self.context_combobox.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 10))
        self.context_combobox.bind('<<ComboboxSelected>>', self.on_context_combobox_select)

        controls_frame = ttk.Frame(context_control_frame)
        controls_frame.grid(row=0, column=2)

        ttk.Button(controls_frame, text="🔄", command=self.refresh_contexts, width=3).pack(side=tk.LEFT, padx=(0, 5))

        self.toggle_logs_button = ttk.Button(controls_frame, text="🔼 Show logs", command=self.toggle_logs_panel)
        self.toggle_logs_button.pack(side=tk.LEFT)

        columns = ('Service', 'Port', 'Namespace', 'Status')
        self.services_tree = ttk.Treeview(services_frame, columns=columns, show='headings', height=15, style='Treeview')

        # Centrar todas las columnas y encabezados
        for col in columns:
            self.services_tree.heading(col, text=col, anchor='center', command=lambda c=col: self.sort_treeview(c))
            self.services_tree.column(col, anchor='center')
        self.services_tree.column('Service', width=240)
        self.services_tree.column('Port', width=100)
        self.services_tree.column('Namespace', width=180)
        self.services_tree.column('Status', width=160)

        services_scrollbar = ttk.Scrollbar(services_frame, orient=tk.VERTICAL, command=self.services_tree.yview)
        self.services_tree.configure(yscrollcommand=services_scrollbar.set)

        self.services_tree.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        services_scrollbar.grid(row=1, column=1, sticky=(tk.N, tk.S))

        self.services_tree.bind('<<TreeviewSelect>>', self.on_service_select)
        self.services_tree.bind('<Double-1>', self.toggle_service)
        self.services_tree.bind('<Return>', self.on_enter_key)
        self.services_tree.bind('<KeyPress>', self.on_key_press)
        self.services_tree.bind('<Double-1>', self.on_treeview_double_click)

        services_buttons_frame = ttk.Frame(services_frame)
        services_buttons_frame.grid(row=2, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(services_buttons_frame, text="▶️ Start", command=self.start_selected_service).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(services_buttons_frame, text="⏹️ Stop", command=self.stop_selected_service).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(services_buttons_frame, text="🚀 Start All", command=self.start_all_services).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(services_buttons_frame, text="🛑 Stop All", command=self.stop_all_services).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(services_buttons_frame, text="📜 Logs", command=self.show_logs).pack(side=tk.LEFT)

    def on_treeview_double_click(self, event):
        region = self.services_tree.identify("region", event.x, event.y)
        if region == "heading":
            return
        item = self.services_tree.selection()
        if item:
            self.on_enter_key(None)

    def sort_treeview(self, column):
        if not self.current_pods:
            return
        if self.sort_column == column:
            self.sort_reverse = not self.sort_reverse
            if not self.sort_reverse:
                self.sort_column = None
                self.update_services_list()
                return
        else:
            self.sort_column = column
            self.sort_reverse = False

        items = []
        for item_id in self.services_tree.get_children():
            values = self.services_tree.item(item_id, 'values')
            items.append((item_id, values))

        column_index = {'Service': 0, 'Port': 1, 'Namespace': 2, 'Status': 3}[column]

        if column == 'Port':
            items.sort(key=lambda x: int(x[1][column_index]) if str(x[1][column_index]).isdigit() else 0,
                       reverse=self.sort_reverse)
        else:
            items.sort(key=lambda x: x[1][column_index], reverse=self.sort_reverse)

        for index, (item_id, _values) in enumerate(items):
            self.services_tree.move(item_id, '', index)

        self.update_column_headers()

    def update_column_headers(self):
        columns = ['Service', 'Port', 'Namespace', 'Status']
        for col in columns:
            if col == self.sort_column:
                symbol = " ↓" if not self.sort_reverse else " ↑"
                self.services_tree.heading(col, text=f"{col}{symbol}")
            else:
                self.services_tree.heading(col, text=col)

    def on_enter_key(self, event):
        selection = self.services_tree.selection()
        if not selection:
            return 'break'
        item = selection[0]
        values = self.services_tree.item(item, 'values')
        service_name = values[0]
        self.current_selection = service_name
        pod = next((p for p in self.current_pods if p.get_service() == service_name), None)
        if pod:
            if pod.is_running():
                self.stop_service_async_with_enter(pod)
            else:
                self.start_service_async_with_enter(pod)
        return 'break'

    def start_service_async_with_enter(self, pod):
        def restore_focus_callback():
            self.root.after(10, self._force_focus_restoration)
            self.root.after(100, self._force_focus_restoration)
            self.root.after(300, self._force_focus_restoration)
        threading.Thread(target=self._start_service_with_focus,
                         args=(pod, restore_focus_callback), daemon=True).start()

    def stop_service_async_with_enter(self, pod):
        def restore_focus_callback():
            self.root.after(10, self._force_focus_restoration)
            self.root.after(100, self._force_focus_restoration)
            self.root.after(300, self._force_focus_restoration)
        threading.Thread(target=self._stop_service_with_focus,
                         args=(pod, restore_focus_callback), daemon=True).start()

    def _force_focus_restoration(self):
        if not self.running or not self.window_has_focus:
            return
        if not self.services_tree.get_children():
            return
        self.services_tree.focus_force()
        if not self.services_tree.selection() and self.current_selection:
            for item_id in self.services_tree.get_children():
                values = self.services_tree.item(item_id, 'values')
                if values and values[0] == self.current_selection:
                    self.services_tree.selection_set(item_id)
                    self.services_tree.focus(item_id)
                    self.services_tree.see(item_id)
                    break
            else:
                first_item = self.services_tree.get_children()[0]
                self.services_tree.selection_set(first_item)
                self.services_tree.focus(first_item)
                self.services_tree.see(first_item)
                values = self.services_tree.item(first_item, 'values')
                if values:
                    self.current_selection = values[0]

    def _ensure_focus_and_selection(self):
        if not self.running or not self.window_has_focus:
            return
        if not self.services_tree.get_children():
            return

        if not self.services_tree.selection() and self.current_selection:
            for item_id in self.services_tree.get_children():
                values = self.services_tree.item(item_id, 'values')
                if values and values[0] == self.current_selection:
                    self.services_tree.selection_set(item_id)
                    self.services_tree.focus(item_id)
                    self.services_tree.see(item_id)
                    break
            else:
                first_item = self.services_tree.get_children()[0]
                self.services_tree.selection_set(first_item)
                self.services_tree.focus(first_item)
                self.services_tree.see(first_item)
                values = self.services_tree.item(first_item, 'values')
                if values:
                    self.current_selection = values[0]
        else:
            sel = self.services_tree.selection()
            if sel:
                self.services_tree.focus(sel[0])

        self.services_tree.focus_set()

    def start_service_async_with_focus(self, pod):
        def restore_focus_callback():
            self.root.after(50, self._ensure_focus_and_selection)
            self.root.after(150, self._ensure_focus_and_selection)
        threading.Thread(target=self._start_service_with_focus,
                         args=(pod, restore_focus_callback), daemon=True).start()

    def stop_service_async_with_focus(self, pod):
        def restore_focus_callback():
            self.root.after(50, self._ensure_focus_and_selection)
            self.root.after(150, self._ensure_focus_and_selection)
        threading.Thread(target=self._stop_service_with_focus,
                         args=(pod, restore_focus_callback), daemon=True).start()

    def _start_service_with_focus(self, pod, callback):
        service_name = pod.get_service()
        self.root.after(0, self.log_message, f"🚀 Starting {service_name}")
        was_running_before = getattr(pod, "_was_running", False)
        try:
            if hasattr(pod, '_start_port_forward') and callable(getattr(pod, '_start_port_forward')):
                success = pod._start_port_forward()
            elif hasattr(pod, 'start_sync') and callable(getattr(pod, 'start_sync')):
                success = pod.start_sync()
            else:
                start_method = getattr(pod, 'start', None)
                if start_method:
                    import asyncio, inspect
                    if inspect.iscoroutinefunction(start_method):
                        try:
                            loop = asyncio.get_event_loop()
                            created = False
                        except RuntimeError:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            created = True
                        try:
                            success = loop.run_until_complete(start_method())
                        finally:
                            if created:
                                loop.close()
                    else:
                        success = start_method()
                else:
                    success = False

            pod_id = f"{pod.get_context()}/{pod.get_namespace()}/{pod.get_service()}"

            if success:
                pod._was_running = True
                if self.pod_monitor:
                    self.pod_monitor.mark_user_started(pod_id)
                    self.notified_disconnected_pods.discard(pod_id)
                    if hasattr(self.pod_monitor, 'recently_failed_pods'):
                        self.pod_monitor.recently_failed_pods.discard(pod_id)
                self.root.after(0, self.log_message, f"✅ {service_name} successfully initiated")
            else:
                if not was_running_before:
                    pod._was_running = False
                    if self.pod_monitor and hasattr(self.pod_monitor, 'recently_failed_pods'):
                        self.pod_monitor.recently_failed_pods.discard(pod_id)
                    self.notified_disconnected_pods.discard(pod_id)
                    self.root.after(0, self.log_message, f"❌ Error at starting {service_name}, staying STOPPED")
                else:
                    self.root.after(0, self.log_message, f"❌ Restart failed for {service_name}; keeping FAILED")

            self.root.after(100, self.update_services_list)

        except Exception as e:
            if not was_running_before:
                pod._was_running = False
                pod_id = f"{pod.get_context()}/{pod.get_namespace()}/{pod.get_service()}"
                if self.pod_monitor and hasattr(self.pod_monitor, 'recently_failed_pods'):
                    self.pod_monitor.recently_failed_pods.discard(pod_id)
                self.notified_disconnected_pods.discard(pod_id)
            self.root.after(0, self.log_message, f"❌ Error at starting {service_name}: {e}")
        finally:
            if callback:
                self.root.after(0, callback)

    def _stop_service_with_focus(self, pod, callback):
        service_name = pod.get_service()
        self.root.after(0, self.log_message, f"🛑 Stopping {service_name}...")
        try:
            success = pod.stop()
            pod._was_running = False
            if self.pod_monitor:
                pod_id = f"{pod.get_context()}/{pod.get_namespace()}/{pod.get_service()}"
                self.pod_monitor.mark_user_stopped(pod_id)
                self.notified_disconnected_pods.discard(pod_id)
            if success:
                self.root.after(0, self.log_message, f"✅ {service_name} successfully stopped")
            else:
                self.root.after(0, self.log_message, f"❌ Error at stopping {service_name}")
        except Exception as e:
            self.root.after(0, self.log_message, f"❌ Error at stopping {service_name}: {e}")
        finally:
            if callback:
                self.root.after(0, callback)

    def start_service_async_with_callback(self, pod, operation_id=None):
        def callback():
            if operation_id and hasattr(self, '_active_operations'):
                self._active_operations.discard(operation_id)
            self.root.after(100, self._ensure_focus_and_selection)
        threading.Thread(target=self._start_service_with_callback,
                         args=(pod, callback), daemon=True).start()

    def stop_service_async_with_callback(self, pod, operation_id=None):
        def callback():
            if operation_id and hasattr(self, '_active_operations'):
                self._active_operations.discard(operation_id)
            self.root.after(100, self._ensure_focus_and_selection)
        threading.Thread(target=self._stop_service_with_callback,
                         args=(pod, callback), daemon=True).start()

    def _start_service_with_callback(self, pod, callback):
        service_name = pod.get_service()
        self.root.after(0, self.log_message, f"🚀 Starting {service_name}")
        was_running_before = getattr(pod, "_was_running", False)
        try:
            if hasattr(pod, 'start') and callable(getattr(pod, 'start')):
                success = pod.start()
            else:
                success = pod._start_port_forward()

            pod_id = f"{pod.get_context()}/{pod.get_namespace()}/{pod.get_service()}"

            if success:
                pod._was_running = True
                if self.pod_monitor:
                    self.pod_monitor.mark_user_started(pod_id)
                    self.notified_disconnected_pods.discard(pod_id)
                    if hasattr(self.pod_monitor, 'recently_failed_pods'):
                        self.pod_monitor.recently_failed_pods.discard(pod_id)
                self.root.after(0, self.log_message, f"✅ {service_name} successfully started")
            else:
                if not was_running_before:
                    pod._was_running = False
                    if self.pod_monitor and hasattr(self.pod_monitor, 'recently_failed_pods'):
                        self.pod_monitor.recently_failed_pods.discard(pod_id)
                    self.notified_disconnected_pods.discard(pod_id)
                    self.root.after(0, self.log_message, f"❌ Error at starting {service_name}, staying STOPPED")
                else:
                    self.root.after(0, self.log_message, f"❌ Restart failed for {service_name}; keeping FAILED")

            self.root.after(100, self.update_services_list)

        except Exception as e:
            if not was_running_before:
                pod._was_running = False
                pod_id = f"{pod.get_context()}/{pod.get_namespace()}/{pod.get_service()}"
                if self.pod_monitor and hasattr(self.pod_monitor, 'recently_failed_pods'):
                    self.pod_monitor.recently_failed_pods.discard(pod_id)
                self.notified_disconnected_pods.discard(pod_id)
            self.root.after(0, self.log_message, f"❌ Error at starting {service_name}: {e}")
        finally:
            if callback:
                self.root.after(0, callback)

    def _stop_service_with_callback(self, pod, callback):
        service_name = pod.get_service()
        self.root.after(0, self.log_message, f"🛑 Stopping {service_name}...")
        try:
            success = pod.stop()
            pod._was_running = False
            if self.pod_monitor:
                pod_id = f"{pod.get_context()}/{pod.get_namespace()}/{pod.get_service()}"
                self.pod_monitor.mark_user_stopped(pod_id)
                self.notified_disconnected_pods.discard(pod_id)
            if success:
                self.root.after(0, self.log_message, f"✅ {service_name} Successfully stopped")
            else:
                self.root.after(0, self.log_message, f"❌ Error at stopping {service_name}")
        except Exception as e:
            self.root.after(0, self.log_message, f"❌ Error at stopping {service_name}: {e}")
        finally:
            if callback:
                self.root.after(0, callback)

    def on_key_press(self, event):
        pass

    def create_status_bar(self):
        status_frame = ttk.Frame(self.main_frame)
        status_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(10, 0))

    def initialize_app(self):
        self.log_message("🚀 Starting KubeWire...")
        threading.Thread(target=self._initialize_async, daemon=True).start()

    def _initialize_async(self):
        try:
            contexts = ConfigManager.read_config()
            context_statuses = []
            if not contexts:
                self.log_message("🔧 Auto-discovering configuration of Kubernetes...")
                contexts, context_statuses = ConfigManager.discover_config()
                if contexts:
                    ConfigManager.save_discovered_config(contexts)
            self.root.after(0, self._update_contexts, contexts, context_statuses)
        except Exception as e:
            self.root.after(0, self.log_message, f"❌ Error during initialisation: {e}")

    def _update_contexts(self, contexts, context_statuses):
        self.contexts = contexts
        self.context_statuses = context_statuses
        self.update_context_combobox()
        accessible_contexts = list(self.contexts.keys())
        context_to_select = None
        if len(accessible_contexts) == 1:
            context_to_select = accessible_contexts[0]
            self.log_message(f"🎯 Self-selected single context: {context_to_select}")
        elif len(accessible_contexts) > 1:
            context_to_select = accessible_contexts[0]
            self.log_message(f"🎯 Selected default context: {context_to_select}")
        if context_to_select:
            self.select_context(context_to_select)
            self._update_combobox_selection(context_to_select)
        accessible_count = len(accessible_contexts)
        inaccessible_count = len([s for s in context_statuses if not s.accessible])
        if accessible_count > 0:
            self.log_message(f"✅ Found {accessible_count} accessible context(s)")
        if inaccessible_count > 0:
            self.log_message(f"⚠️ Found {inaccessible_count} inaccessible context(s)")

    def update_context_combobox(self):
        self.context_combobox['values'] = []
        context_list = []
        for context_name in self.contexts.keys():
            service_count = len(self.contexts[context_name])
            context_list.append(f"{context_name} ({service_count} services)")
        for status in self.context_statuses:
            if not status.accessible:
                context_list.append(f"{status.name} (⚠️ No accesible)")
        self.context_combobox['values'] = context_list

    def _update_combobox_selection(self, context_name):
        context_list = self.context_combobox['values']
        for i, context_display in enumerate(context_list):
            if context_display.startswith(context_name + " ("):
                self.context_combobox.current(i)
                self.context_var.set(context_display)
                break

    def on_context_combobox_select(self, event):
        selected_display = self.context_var.get()
        if not selected_display:
            return
        context_name = selected_display.split(" (")[0]
        if context_name in self.contexts:
            self.select_context(context_name)
        else:
            messagebox.showwarning("Inaccessible Context",
                                   f"Context cannot be accessed '{context_name}'.\n"
                                   f"Check your kubectl")
            if self.current_context:
                for i, context_display in enumerate(self.context_combobox['values']):
                    if context_display.startswith(self.current_context):
                        self.context_combobox.current(i)
                        break

    def select_context(self, context_name):
        if context_name not in self.contexts:
            return
        if self.current_context and self.current_context != context_name:
            self.stop_all_services()
        if self.pod_monitor:
            self.pod_monitor.stop_monitoring()
        self.sort_column = None
        self.sort_reverse = False
        self.original_order = []
        self.current_context = context_name
        self.current_pods = self.contexts[context_name]
        self.notified_disconnected_pods.clear()
        self.current_selection = None
        for pod in self.current_pods:
            pod._was_running = pod.is_running()
        self.pod_monitor = PodMonitor(self)
        self.pod_monitor.start_monitoring()
        self.update_services_list()
        self.log_message(f"📋 Selected context: {context_name}")
        self.start_auto_refresh()

    def on_service_select(self, event):
        selection = self.services_tree.selection()
        if selection:
            item = selection[0]
            values = self.services_tree.item(item, 'values')
            if values:
                self.current_selection = values[0]
        else:
            self.current_selection = None

    def update_services_list(self):
        if not self.current_pods:
            return
        had_focus = self.services_tree == self.root.focus_get()
        prev_sel = self.current_selection
        existing = {self.services_tree.item(iid, 'values')[0]: iid for iid in self.services_tree.get_children()}
        new_failed_pods = []
        rows = []
        for pod in self.current_pods:
            pod_id = f"{pod.get_context()}/{pod.get_namespace()}/{pod.get_service()}"
            running = pod.is_running()
            failed = self._is_pod_failed(pod)
            if failed:
                status, tags = "💥 FAILED", ('failed',)
                if pod_id not in self.notified_disconnected_pods:
                    new_failed_pods.append(pod_id)
            elif running:
                status, tags = "🟢 RUNNING", ('running',)
            else:
                status, tags = "🔴 STOPPED", ('stopped',)
            rows.append((pod.get_service(), pod.get_port(), pod.get_namespace(), status, tags))
        if self.sort_column:
            idx = {'Service': 0, 'Port': 1, 'Namespace': 2, 'Status': 3}[self.sort_column]
            if self.sort_column == 'Port':
                rows.sort(key=lambda r: int(r[idx]), reverse=self.sort_reverse)
            else:
                rows.sort(key=lambda r: r[idx], reverse=self.sort_reverse)
        self._service_to_item = {}
        updated_services = set()
        for svc, port, ns, status, tags in rows:
            if svc in existing:
                iid = existing[svc]
                self.services_tree.item(iid, values=(svc, port, ns, status), tags=tags)
            else:
                iid = self.services_tree.insert('', tk.END, values=(svc, port, ns, status), tags=tags)
            self._service_to_item[svc] = iid
            updated_services.add(svc)
        for svc, iid in existing.items():
            if svc not in updated_services:
                self.services_tree.delete(iid)
        self.services_tree.tag_configure('running', foreground=SOLARIZED['green'], font=('Arial', 13, 'bold'))
        self.services_tree.tag_configure('stopped', foreground=SOLARIZED['red'], font=('Arial', 13, 'bold'))
        self.services_tree.tag_configure('failed', foreground=SOLARIZED['orange'], font=('Arial', 13, 'bold'))

        if prev_sel and prev_sel in self._service_to_item:
            iid = self._service_to_item[prev_sel]
            self.services_tree.selection_set(iid)
            self.services_tree.focus(iid)
            self.services_tree.see(iid)
            self.current_selection = prev_sel
        elif rows:
            first_iid = self._service_to_item[rows[0][0]]
            self.services_tree.selection_set(first_iid)
            self.services_tree.focus(first_iid)
            self.services_tree.see(first_iid)
            self.current_selection = rows[0][0]

        if had_focus or not self._initial_focus_done:
            self.services_tree.focus_set()

        if not self._initial_focus_done and self.services_tree.get_children():
            self._initial_focus_done = True

        if new_failed_pods and self.sound_enabled:
            threading.Thread(target=self.sound_notifier.play_disconnect_sound, daemon=True).start()
            self.notified_disconnected_pods.update(new_failed_pods)
        self.update_column_headers()

    def start_auto_refresh(self):
        self.stop_auto_refresh()
        self._auto_refresh()

    def stop_auto_refresh(self):
        if self.refresh_timer:
            self.root.after_cancel(self.refresh_timer)
            self.refresh_timer = None

    def _auto_refresh(self):
        if not (self.running and self.current_context):
            return
        focused = self.root.focus_get()
        if focused == self.services_tree:
            current = {p.get_service(): (p.is_running(), self._is_pod_failed(p)) for p in self.current_pods}
            if not hasattr(self, '_last_states') or self._last_states != current:
                self._last_states = current
                self.update_services_list()
        else:
            self.update_services_list()
        self.refresh_timer = self.root.after(2000, self._auto_refresh)

    def toggle_service(self, event):
        selection = self.services_tree.selection()
        if not selection:
            return
        item = selection[0]
        values = self.services_tree.item(item, 'values')
        service_name = values[0]
        pod = next((p for p in self.current_pods if p.get_service() == service_name), None)
        if pod:
            if pod.is_running():
                self.stop_service_async(pod)
            else:
                self.start_service_async(pod)

    def start_selected_service(self):
        selection = self.services_tree.selection()
        if not selection:
            messagebox.showwarning("No Selection", "Select a service first")
            self.root.after(50, self._ensure_focus_and_selection)
            return
        item = selection[0]
        values = self.services_tree.item(item, 'values')
        service_name = values[0]
        self.current_selection = service_name
        pod = next((p for p in self.current_pods if p.get_service() == service_name), None)
        if pod:
            self.start_service_async(pod)
        self.services_tree.focus_set()

    def stop_selected_service(self):
        selection = self.services_tree.selection()
        if not selection:
            messagebox.showwarning("No Selection", "Select a service first")
            self.root.after(50, self._ensure_focus_and_selection)
            return
        item = selection[0]
        values = self.services_tree.item(item, 'values')
        service_name = values[0]
        self.current_selection = service_name
        pod = next((p for p in self.current_pods if p.get_service() == service_name), None)
        if pod:
            self.stop_service_async(pod)
        self.services_tree.focus_set()

    def start_service_async(self, pod):
        threading.Thread(target=self._start_service, args=(pod,), daemon=True).start()

    def _start_service(self, pod):
        service_name = pod.get_service()
        self.root.after(0, self.log_message, f"🚀 Starting {service_name}")
        was_running_before = getattr(pod, "_was_running", False)
        try:
            success = False
            if hasattr(pod, '_start_port_forward') and callable(getattr(pod, '_start_port_forward')):
                success = pod._start_port_forward()
            elif hasattr(pod, 'start_sync') and callable(getattr(pod, 'start_sync')):
                success = pod.start_sync()
            else:
                start_method = getattr(pod, 'start', None)
                if start_method:
                    import asyncio, inspect
                    if inspect.iscoroutinefunction(start_method):
                        try:
                            loop = asyncio.get_event_loop()
                            created = False
                        except RuntimeError:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            created = True
                        try:
                            success = loop.run_until_complete(start_method())
                        finally:
                            if created:
                                loop.close()
                    else:
                        success = start_method()

            pod_id = f"{pod.get_context()}/{pod.get_namespace()}/{pod.get_service()}"

            if success:
                pod._was_running = True
                if self.pod_monitor:
                    self.pod_monitor.mark_user_started(pod_id)
                    self.notified_disconnected_pods.discard(pod_id)
                    if hasattr(self.pod_monitor, 'recently_failed_pods'):
                        self.pod_monitor.recently_failed_pods.discard(pod_id)
                self.root.after(0, self.log_message, f"✅ {service_name} successfully initiated")
            else:
                if not was_running_before:
                    pod._was_running = False
                    if self.pod_monitor and hasattr(self.pod_monitor, 'recently_failed_pods'):
                        self.pod_monitor.recently_failed_pods.discard(pod_id)
                    self.notified_disconnected_pods.discard(pod_id)
                    self.root.after(0, self.log_message, f"❌ Error at starting {service_name}, staying STOPPED")
                else:
                    self.root.after(0, self.log_message, f"❌ Restart failed for {service_name}; keeping FAILED")

            self.root.after(100, self.update_services_list)
            self.root.after(200, self._ensure_focus_and_selection)
        except Exception as e:
            if not was_running_before:
                pod._was_running = False
                pod_id = f"{pod.get_context()}/{pod.get_namespace()}/{pod.get_service()}"
                if self.pod_monitor and hasattr(self.pod_monitor, 'recently_failed_pods'):
                    self.pod_monitor.recently_failed_pods.discard(pod_id)
                self.notified_disconnected_pods.discard(pod_id)
            self.root.after(0, self.log_message, f"❌ Error at starting {service_name}: {e}")
            self.root.after(100, self._ensure_focus_and_selection)

    def stop_service_async(self, pod):
        threading.Thread(target=self._stop_service, args=(pod,), daemon=True).start()

    def _stop_service(self, pod):
        service_name = pod.get_service()
        if not pod._was_running:
            self.log_message(f"ℹ️ {service_name} already stopped")
            self.root.after(50, self._ensure_focus_and_selection)
            return
        self.root.after(0, self.log_message, f"🛑 Stopping {service_name}...")
        success = pod.stop()
        if self.pod_monitor:
            pod_id = f"{pod.get_context()}/{pod.get_namespace()}/{pod.get_service()}"
            self.pod_monitor.mark_user_stopped(pod_id)
            self.notified_disconnected_pods.discard(pod_id)
        if success:
            self.root.after(0, self.log_message, f"✅ {service_name} stopped correctly")
            pod._was_running = False
        else:
            self.root.after(0, self.log_message, f"❌ Error at stopping {service_name}")
        self.root.after(100, self._ensure_focus_and_selection)

    def start_all_services(self):
        if not self.current_pods:
            return
        stopped_pods = [pod for pod in self.current_pods if not pod.is_running()]
        if not stopped_pods:
            messagebox.showinfo("Information", "All services are already running")
            self.root.after(50, self._ensure_focus_and_selection)
            return
        self.log_message(f"🚀 Starting {len(stopped_pods)} service(s)...")
        for pod in stopped_pods:
            self.start_service_async(pod)
        self.services_tree.focus_set()

    def stop_all_services(self):
        if not self.current_pods:
            self.log_message("ℹ️  No services found")
            return

        running_pods = [pod for pod in self.current_pods if pod.is_running()]
        if not running_pods:
            self.log_message("ℹ️ All services are already stopped")
            self.root.after(50, self._ensure_focus_and_selection)
            return

        self.log_message(f"🛑 Stopping {len(running_pods)} service(s)...")
        for pod in running_pods:
            self.stop_service_async(pod)

        self.services_tree.focus_set()


    def show_logs(self):
        selection = self.services_tree.selection()
        if not selection:
            messagebox.showwarning("No selection", "Select a service first")
            self.root.after(50, self._ensure_focus_and_selection)
            return
        item = selection[0]
        values = self.services_tree.item(item, 'values')
        service_name = values[0]
        self.current_selection = service_name
        pod = next((p for p in self.current_pods if p.get_service() == service_name), None)
        if pod:
            self.show_pod_logs_async(pod)
        self.services_tree.focus_set()

    def show_pod_logs_async(self, pod):
        self.clear_logs()

        if not self.logs_frame.winfo_ismapped():
            self.logs_frame.grid(row=3, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=10, pady=(5, 0))
            self.main_frame.rowconfigure(3, weight=1)
            self.toggle_logs_button.config(text="🔽 Hide logs")

        threading.Thread(target=self._stream_pod_logs_to_gui, args=(pod,), daemon=True).start()


    def _stream_pod_logs_to_gui(self, pod):
        context = pod.get_context()
        namespace = pod.get_namespace()
        service = pod.get_service()

        if self._is_stern_available():
            cmd = ["stern", "-n", namespace, "-l", f"app={service}", "--since", "1h"]
        else:
            cmd = ["kubectl", "logs", "-n", namespace, "-l", f"app={service}", "--since=1h", "--tail=100", "--follow"]

        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

            def update_logs():
                for line in process.stdout:
                    self.root.after(0, self._append_log_line, line)

            threading.Thread(target=update_logs, daemon=True).start()
            self.root.after(0, self.log_message, f"📜 Showing logs for {service} in the GUI...")
        except Exception as e:
            self.root.after(0, self.log_message, f"❌ Error retrieving logs: {e}")

    def _append_log_line(self, line):
        if self.logs_text:
            self.logs_text.configure(state='normal')
            self.logs_text.insert(tk.END, line)
            self.logs_text.see(tk.END)
            self.logs_text.configure(state='disabled')

    def clear_logs(self):
        self.logs_text.configure(state='normal')
        self.logs_text.delete('1.0', tk.END)
        self.logs_text.configure(state='disabled')


    def _is_stern_available(self) -> bool:
        try:
            subprocess.run(["stern", "--version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return True
        except Exception:
            return False

    def _is_pod_failed(self, pod):
        pod_id = f"{pod.get_context()}/{pod.get_namespace()}/{pod.get_service()}"
        previously_running = getattr(pod, "_was_running", False)

        if not previously_running:
            return False

        recently_failed = False
        if self.pod_monitor and hasattr(self.pod_monitor, "recently_failed_pods"):
            recently_failed = pod_id in self.pod_monitor.recently_failed_pods

        return recently_failed or (not pod.is_running())

    def _update_contexts_and_restore(self, contexts, context_statuses, restore_context):
        self.contexts = contexts
        self.context_statuses = context_statuses
        self.update_context_combobox()
        if restore_context in contexts:
            self.select_context(restore_context)
            self._update_combobox_selection(restore_context)
            self.log_message(f"🔄 Restored context: {restore_context}")
        else:
            accessible_contexts = list(self.contexts.keys())
            if accessible_contexts:
                context_to_select = accessible_contexts[0]
                self.select_context(context_to_select)
                self._update_combobox_selection(context_to_select)
        self.update_status("Done")

    def refresh_contexts(self):
        self.show_loading_overlay("Updating contexts...")
        self.log_message("🔄 Updating configuration...")
        threading.Thread(target=self._refresh_contexts_async, daemon=True).start()


    def _refresh_contexts_async(self):
        try:
            new_contexts, new_statuses = ConfigManager.discover_config()
            if new_contexts:
                previous_context = self.current_context
                if self.current_context and any(pod.is_running() for pod in self.current_pods):
                    self.stop_all_services()
                ConfigManager.save_discovered_config(new_contexts)
                if previous_context and previous_context in new_contexts:
                    self.root.after(0, self._update_contexts_and_restore, new_contexts, new_statuses, previous_context)
                else:
                    self.root.after(0, self._update_contexts, new_contexts, new_statuses)
                self.root.after(0, self.log_message, "✅ Updated configuration")
                self.root.after(0, self.hide_loading_overlay)
            else:
                self.root.after(0, self.log_message, "⚠️ No accessible contexts were found")
        except Exception as e:
            self.root.after(0, self.log_message, f"❌ Error at updating: {e}")
            self.root.after(0, self.hide_loading_overlay)

    def show_loading_overlay(self, text="Cargando..."):
        if hasattr(self, "_loading_overlay") and self._loading_overlay:
            return

        self._loading_overlay = tk.Toplevel(self.root)
        self._loading_overlay.overrideredirect(True)
        self._loading_overlay.attributes("-alpha", 0.85)
        self._loading_overlay.configure(bg=SOLARIZED['base02'])

        w, h = self.root.winfo_width(), self.root.winfo_height()
        x, y = self.root.winfo_x(), self.root.winfo_y()
        self._loading_overlay.geometry(f"{w}x{h}+{x}+{y}")

        frame = ttk.Frame(self._loading_overlay, padding=20)
        frame.place(relx=0.5, rely=0.5, anchor="center")

        label = ttk.Label(frame, text=text, font=("Arial", 16, "bold"), foreground=SOLARIZED['blue'])
        label.pack(pady=10)

        self._spinner_label = ttk.Label(frame, text="⏳", font=("Arial", 30))
        self._spinner_label.pack()

        self._spinner_running = True
        self._animate_spinner()

        self._loading_overlay.transient(self.root)
        self._loading_overlay.grab_set()

    def hide_loading_overlay(self):
        if hasattr(self, "_loading_overlay") and self._loading_overlay:
            self._spinner_running = False
            self._loading_overlay.grab_release()
            self._loading_overlay.destroy()
            self._loading_overlay = None

    def _animate_spinner(self):
        if not self._spinner_running:
            return
        frames = ["⏳", "⌛", "🔄", "🌀"]
        current = frames.pop(0)
        frames.append(current)
        self._spinner_label.config(text=current)
        self.root.after(300, self._animate_spinner)

    def log_message(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        full_message = f"[{timestamp}] {message}\n"
        try:
            print(full_message, end='')
        except Exception:
            pass
        if self.logs_text is not None:
            try:
                self.logs_text.configure(state='normal')
                self.logs_text.insert(tk.END, full_message)
                self.logs_text.see(tk.END)
                self.logs_text.configure(state='disabled')
            except Exception:
                pass

    def update_status(self, status):
        self.status_label.config(text=status)

    def request_refresh(self):
        if self.running:
            self.root.after(0, self.update_services_list)

    def trigger_refresh_with_failures(self, failed_pods):
        if failed_pods and self.sound_enabled:
            threading.Thread(target=self.sound_notifier.play_disconnect_sound, daemon=True).start()
            for pod_id in failed_pods:
                self.notified_disconnected_pods.add(pod_id)
        self.request_refresh()

    def stop_all_services_blocking(self):
        """Detiene todos los servicios de forma síncrona y segura."""
        if not self.current_pods:
            return
        for pod in self.current_pods:
            try:
                if pod.is_running():
                    self.log_message(f"🛑 Stopping {pod.get_service()} (blocking)...")
                    pod.stop()
                    pod._was_running = False
            except Exception as e:
                self.log_message(f"❌ Error stopping {pod.get_service()}: {e}")

    def on_closing(self):
        self.log_message("👋 Closing application...")
        self.running = False
        try:
            # Deshabilita la ventana para evitar interacción
            self.root.withdraw()
            self.root.update()
        except Exception:
            pass
        try:
            self.stop_all_services_blocking()
        except Exception as e:
            self.log_message(f"⚠️ Error stopping services: {e}")
        if self.pod_monitor:
            try:
                if hasattr(self.pod_monitor, "stop"):
                    self.pod_monitor.stop()
                else:
                    self.log_message("ℹ️ Pod monitor has no stop method")
            except Exception as e:
                self.log_message(f"⚠️ Error stopping pod monitor: {e}")
        try:
            self.stop_auto_refresh()  # <--- CANCELA EL AUTO REFRESH ANTES DE DESTRUIR LA VENTANA
        except Exception:
            pass
        try:
            self.root.quit()
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        self.root.mainloop()
