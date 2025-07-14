import os
import subprocess
import sys


class SoundNotifier:

    @staticmethod
    def play_disconnect_sound():
        try:
            if sys.platform == "darwin":
                subprocess.run(["afplay", "/System/Library/Sounds/Sosumi.aiff"],
                               check=False, timeout=2)
            elif sys.platform == "win32":
                import winsound
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            else:
                methods = [
                    ["paplay", "/usr/share/sounds/alsa/Front_Left.wav"],
                    ["aplay", "/usr/share/sounds/alsa/Front_Left.wav"],
                    ["speaker-test", "-t", "sine", "-f", "1000", "-l", "1"],
                    ["beep", "-f", "800", "-l", "200"],
                    ["printf", "\a"]
                ]

                for method in methods:
                    try:
                        subprocess.run(method, check=True, timeout=2,
                                       stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL)
                        break
                    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
                        continue

        except ImportError:
            if sys.platform == "win32":
                try:
                    subprocess.run(["powershell", "-c", "[console]::beep(800,200)"],
                                   check=False, timeout=2)
                except:
                    pass
        except Exception:
            pass

    @staticmethod
    def is_sound_available():
        try:
            if sys.platform == "darwin":
                return os.path.exists("/System/Library/Sounds/Sosumi.aiff")
            elif sys.platform == "win32":
                try:
                    import winsound
                    return True
                except ImportError:
                    return True
            else:
                methods = ["paplay", "aplay", "speaker-test", "beep"]
                for method in methods:
                    try:
                        subprocess.run(["which", method], check=True,
                                       stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL)
                        return True
                    except subprocess.CalledProcessError:
                        continue
                return True
        except:
            return False
