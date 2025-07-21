import queue
import subprocess
import threading
import tkinter as tk


class LogsManager:
    def __init__(self, gui_instance):
        self.gui = gui_instance
        self.current_process = None
        self.log_queue = queue.Queue()
        self.is_streaming = False
        self._stream_thread = None
        self._lock = threading.Lock()
    
    def show_pod_logs_async(self, pod):
        """Muestra los logs de un pod en tiempo real"""
        # Detener cualquier streaming anterior
        self.stop_current_streaming()
        
        # Limpiar logs anteriores SOLO en el widget de logs
        self.gui.clear_logs()
        
        # Mostrar panel de logs si está oculto
        if not self.gui.logs_frame.winfo_ismapped():
            self.gui.logs_frame.grid(row=3, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=10, pady=(5, 0))
            self.gui.main_frame.rowconfigure(3, weight=1)
            self.gui.toggle_logs_button.config(text="🔽 Hide logs")
        
        # Iniciar streaming en hilo separado
        self.is_streaming = True
        self._stream_thread = threading.Thread(target=self._stream_logs, args=(pod,), daemon=True)
        self._stream_thread.start()
        
        # Iniciar procesamiento de cola de logs
        self.gui.root.after(100, self._process_log_queue)
    
    def _stream_logs(self, pod):
        """Ejecuta el comando de logs y procesa la salida línea por línea"""
        context = pod.get_context()
        namespace = pod.get_namespace()
        service = pod.get_service()
        
        # Construir comando
        if self._is_stern_available():
            cmd = ["stern", "-n", namespace, "-l", f"app={service}", "--since", "1h", "--color", "never"]
        else:
            cmd = ["kubectl", "logs", "-n", namespace, "-l", f"app={service}", 
                   "--since=1h", "--tail=100", "--follow", "--timestamps"]
        
        try:
            # Mensaje inicial SOLO en terminal
            print(f"📜 Iniciando logs para {service} en namespace {namespace}...\n" + "-" * 80)
            
            # Ejecutar comando
            with self._lock:
                self.current_process = subprocess.Popen(
                    cmd, 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.STDOUT, 
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )
            
            # Leer línea por línea
            for line in iter(self.current_process.stdout.readline, ''):
                if not self.is_streaming:
                    break
                if line.strip():  # Solo agregar líneas no vacías
                    self.log_queue.put(line)
            
        except subprocess.CalledProcessError as e:
            print(f"❌ Error ejecutando comando de logs: {e}")
        except FileNotFoundError as e:
            print(f"❌ Comando no encontrado: {e}\n💡 Asegúrate de tener kubectl instalado y configurado")
        except Exception as e:
            print(f"❌ Error inesperado: {e}")
        finally:
            with self._lock:
                if self.current_process:
                    try:
                        self.current_process.terminate()
                        self.current_process.wait(timeout=5)
                    except:
                        try:
                            self.current_process.kill()
                        except:
                            pass
                    self.current_process = None
    
    def _process_log_queue(self):
        """Procesa la cola de logs y actualiza la GUI de forma segura"""
        try:
            # Procesar hasta 10 líneas por ciclo para no bloquear la GUI
            for _ in range(10):
                try:
                    line = self.log_queue.get_nowait()
                    self._append_log_line(line)
                except queue.Empty:
                    break
                    
        except Exception as e:
            print(f"Error procesando cola de logs: {e}")
        
        # Continuar procesando si aún estamos streaming y la GUI sigue activa
        if self.is_streaming and getattr(self.gui, 'running', True):
            self.gui.root.after(100, self._process_log_queue)
    
    def _append_log_line(self, line):
        """Agrega una línea al widget de texto de logs"""
        if not hasattr(self.gui, 'append_service_log'):
            return
        try:
            self.gui.append_service_log(line)
        except Exception as e:
            print(f"Error agregando línea de log: {e}")

    def stop_current_streaming(self):
        """Detiene el streaming actual de logs"""
        self.is_streaming = False
        with self._lock:
            if self.current_process:
                try:
                    self.current_process.terminate()
                    self.current_process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    try:
                        self.current_process.kill()
                        self.current_process.wait(timeout=2)
                    except:
                        pass
                except:
                    pass
                finally:
                    self.current_process = None
        # Esperar a que el hilo termine (si existe)
        if self._stream_thread and self._stream_thread.is_alive():
            self._stream_thread.join(timeout=2)
        self._stream_thread = None
    
    def _is_stern_available(self):
        """Verifica si stern está disponible"""
        try:
            subprocess.run(["stern", "--version"], 
                         check=True, 
                         stdout=subprocess.PIPE, 
                         stderr=subprocess.PIPE,
                         timeout=5)
            return True
        except:
            return False