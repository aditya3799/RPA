"""
macOS Floating RPA UI with hotkey support
Press Ctrl+Shift+Space to toggle the command input
"""

import sys
import threading
import time
from typing import Optional, Callable
from dataclasses import dataclass
from enum import Enum

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QLabel, QStackedWidget
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QThread
from PyQt6.QtGui import QFont, QColor, QPalette, QKeyEvent
from pynput import keyboard

from agent import run_agent


class UIState(Enum):
    IDLE = "idle"
    LOADING = "loading"
    SUCCESS = "success"
    ERROR = "error"


@dataclass
class AgentResult:
    success: bool
    message: str
    steps: int


class InputLineEdit(QLineEdit):
    """Custom QLineEdit that handles Escape key"""
    escape_pressed = pyqtSignal()
    
    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self.escape_pressed.emit()
        else:
            super().keyPressEvent(event)


class AgentWorker(QThread):
    """Run agent in background thread"""
    finished = pyqtSignal(AgentResult)
    error = pyqtSignal(str)

    def __init__(self, objective: str):
        super().__init__()
        self.objective = objective

    def run(self):
        try:
            result = run_agent(self.objective)
            steps = len(result.get("history", []))
            success = result.get("completed", False)
            message = result.get("final_response", "Task executed")
            
            self.finished.emit(AgentResult(
                success=success,
                message=message,
                steps=steps
            ))
        except Exception as e:
            self.error.emit(f"Error: {str(e)}")


class FloatingRPAWindow(QMainWindow):
    toggle_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.worker: Optional[AgentWorker] = None
        self.current_state = UIState.IDLE
        self.is_icon_mode = False
        
        self.setup_ui()
        self.setup_hotkey()
        
        self.toggle_signal.connect(self.toggle_mode)
        self.set_icon_mode()
        self.show()
        
        self._setup_mac_window_behavior()

    def _setup_mac_window_behavior(self):
        """Set specific macOS window properties to persist above full-screen apps"""
        if sys.platform != 'darwin':
            return
        try:
            import ctypes
            from ctypes import c_void_p
            
            objc = ctypes.cdll.LoadLibrary('/usr/lib/libobjc.A.dylib')
            
            objc.objc_getClass.restype = c_void_p
            objc.sel_registerName.restype = c_void_p
            objc.objc_msgSend.restype = c_void_p
            objc.objc_msgSend.argtypes = [c_void_p, c_void_p]
            
            # Cast msgSend for NSUInteger/NSInteger arguments (c_ulonglong/c_longlong)
            msgSend_int = ctypes.cast(objc.objc_msgSend, ctypes.CFUNCTYPE(c_void_p, c_void_p, c_void_p, ctypes.c_longlong))
            
            # Get NSView pointer from PyQt winId()
            view = c_void_p(int(self.winId()))
            
            # NSWindow *window = [view window];
            window_sel = objc.sel_registerName(b"window")
            window = objc.objc_msgSend(view, window_sel)
            
            if window:
                # [window setCollectionBehavior: 273];
                # 273 = NSWindowCollectionBehaviorCanJoinAllSpaces (1<<0) | 
                #       NSWindowCollectionBehaviorStationary (1<<4) |
                #       NSWindowCollectionBehaviorFullScreenAuxiliary (1<<8)
                setCollectionBehavior_sel = objc.sel_registerName(b"setCollectionBehavior:")
                msgSend_int(window, setCollectionBehavior_sel, 273)
                
                # [window setLevel: 101]; (NSPopUpMenuWindowLevel)
                setLevel_sel = objc.sel_registerName(b"setLevel:")
                msgSend_int(window, setLevel_sel, 101)
        except Exception as e:
            print(f"Mac window behavior setup failed: {e}")

    def setup_ui(self):
        """Create the main UI"""
        self.setWindowTitle("RPA Agent Control")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        
        self.stacked_widget = QStackedWidget()
        self.setCentralWidget(self.stacked_widget)
        
        # ---------------- FULL UI WIDGET ----------------
        self.full_widget = QWidget()
        self.full_widget.setObjectName("FullWidget")
        
        layout = QVBoxLayout(self.full_widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        
        # Title label
        title = QLabel("RPA Agent Command Input")
        title_font = QFont("SF Pro Display", 14, QFont.Weight.Bold)
        title.setFont(title_font)
        title.setStyleSheet("color: #FFFFFF;")
        layout.addWidget(title)
        
        # Input container
        input_container = QHBoxLayout()
        
        # Input field
        self.input_field = InputLineEdit()
        self.input_field.setPlaceholderText("Enter objective... (Escape to hide)")
        self.input_field.setFixedHeight(44)
        input_font = QFont("SF Pro Display", 13)
        self.input_field.setFont(input_font)
        self.input_field.returnPressed.connect(self.execute_command)
        self.input_field.escape_pressed.connect(self.set_icon_mode)
        self.input_field.setStyleSheet("""
            QLineEdit {
                background-color: #2a2a2a;
                border: 1px solid #404040;
                border-radius: 8px;
                padding: 8px 12px;
                color: #FFFFFF;
                selection-background-color: #0066CC;
            }
            QLineEdit:focus {
                border: 2px solid #0066CC;
            }
        """)
        input_container.addWidget(self.input_field)
        
        # Execute button
        self.exec_button = QPushButton("Execute")
        self.exec_button.setFixedWidth(100)
        self.exec_button.setFixedHeight(44)
        self.exec_button.setFont(QFont("SF Pro Display", 12, QFont.Weight.Bold))
        self.exec_button.clicked.connect(self.execute_command)
        self.exec_button.setStyleSheet("""
            QPushButton {
                background-color: #0066CC;
                color: white;
                border: none;
                border-radius: 8px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0052A3;
            }
            QPushButton:pressed {
                background-color: #003D7A;
            }
        """)
        input_container.addWidget(self.exec_button)
        
        layout.addLayout(input_container)
        
        # Status label
        self.status_label = QLabel("Ready")
        status_font = QFont("SF Pro Display", 11)
        self.status_label.setFont(status_font)
        self.status_label.setStyleSheet("color: #B0B0B0;")
        layout.addWidget(self.status_label)
        
        self.stacked_widget.addWidget(self.full_widget)
        
        # ---------------- ICON UI WIDGET ----------------
        self.icon_widget = QWidget()
        self.icon_widget.setObjectName("IconWidget")
        icon_layout = QVBoxLayout(self.icon_widget)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        
        self.icon_button = QPushButton("🤖")
        icon_font = QFont("SF Pro Display", 32)
        self.icon_button.setFont(icon_font)
        self.icon_button.setFixedSize(60, 60)
        self.icon_button.clicked.connect(self.set_full_mode)
        self.icon_button.setStyleSheet("""
            QPushButton {
                background-color: #1e1e1e;
                color: white;
                border: 2px solid #404040;
                border-radius: 30px;
            }
            QPushButton:hover {
                background-color: #2a2a2a;
                border: 2px solid #0066CC;
            }
        """)
        icon_layout.addWidget(self.icon_button)
        self.stacked_widget.addWidget(self.icon_widget)
        
        # Apply dark theme
        self.apply_dark_theme()

    def apply_dark_theme(self):
        """Apply dark theme to window"""
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#FFFFFF"))
        self.setPalette(palette)
        
        self.setStyleSheet("""
            QWidget#FullWidget {
                background-color: #1e1e1e;
                border: 1px solid #404040;
                border-radius: 12px;
            }
            QWidget#IconWidget {
                background-color: transparent;
            }
        """)

    def setup_hotkey(self):
        """Setup global hotkey Ctrl+Shift+Space"""
        def detect_hotkey():
            ctrl_pressed = False
            shift_pressed = False
            
            def on_press(key):
                nonlocal ctrl_pressed, shift_pressed
                try:
                    if key == keyboard.Key.ctrl_l or key == keyboard.Key.ctrl_r:
                        ctrl_pressed = True
                    elif key == keyboard.Key.shift:
                        shift_pressed = True
                except (AttributeError, ValueError):
                    pass

            def on_release(key):
                nonlocal ctrl_pressed, shift_pressed
                try:
                    if key == keyboard.Key.ctrl_l or key == keyboard.Key.ctrl_r:
                        ctrl_pressed = False
                    elif key == keyboard.Key.shift:
                        shift_pressed = False
                    elif key == keyboard.Key.space and ctrl_pressed and shift_pressed:
                        # Toggle window mode via signal
                        self.toggle_signal.emit()
                except (AttributeError, ValueError):
                    pass

            listener = keyboard.Listener(on_press=on_press, on_release=on_release)
            listener.start()

        hotkey_thread = threading.Thread(target=detect_hotkey, daemon=True)
        hotkey_thread.start()

    def center_on_screen(self):
        """Center window on screen"""
        screen_geometry = QApplication.primaryScreen().geometry()
        window_geometry = self.frameGeometry()
        center_point = screen_geometry.center()
        window_geometry.moveCenter(center_point)
        self.move(window_geometry.topLeft())

    def toggle_mode(self):
        """Switch between icon and full mode"""
        if self.is_icon_mode:
            self.set_full_mode()
        else:
            self.set_icon_mode()
            
    def set_icon_mode(self):
        """Switch to icon mode"""
        self.is_icon_mode = True
        self.stacked_widget.setCurrentWidget(self.icon_widget)
        self.setFixedSize(60, 60)
        
    def set_full_mode(self):
        """Switch to full UI mode"""
        self.is_icon_mode = False
        self.stacked_widget.setCurrentWidget(self.full_widget)
        self.setFixedSize(700, 120)
        self.center_on_screen()
        self.input_field.setFocus()

    def execute_command(self):
        """Execute the entered command"""
        objective = self.input_field.text().strip()
        if not objective:
            self.status_label.setText("Please enter an objective")
            return

        self.set_state(UIState.LOADING)
        self.status_label.setText("🔄 Agent is working...")
        self.exec_button.setEnabled(False)
        self.input_field.setEnabled(False)

        # Run agent in background
        self.worker = AgentWorker(objective)
        self.worker.finished.connect(self.on_agent_finished)
        self.worker.error.connect(self.on_agent_error)
        self.worker.start()

    def on_agent_finished(self, result: AgentResult):
        """Called when agent finishes"""
        self.set_state(UIState.SUCCESS)
        message = f"✅ Completed in {result.steps} steps"
        self.status_label.setText(message)
        self.input_field.clear()
        self.exec_button.setEnabled(True)
        self.input_field.setEnabled(True)
        
        # Auto-hide after 3 seconds
        QTimer.singleShot(3000, self.set_icon_mode)

    def on_agent_error(self, error: str):
        """Called when agent errors"""
        self.set_state(UIState.ERROR)
        self.status_label.setText(f"❌ {error}")
        self.exec_button.setEnabled(True)
        self.input_field.setEnabled(True)

    def set_state(self, state: UIState):
        """Update UI state and button color"""
        self.current_state = state
        
        if state == UIState.IDLE:
            self.exec_button.setStyleSheet("""
                QPushButton {
                    background-color: #0066CC;
                    color: white;
                    border: none;
                    border-radius: 8px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #0052A3;
                }
            """)
        elif state == UIState.LOADING:
            self.exec_button.setStyleSheet("""
                QPushButton {
                    background-color: #FF9500;
                    color: white;
                    border: none;
                    border-radius: 8px;
                    font-weight: bold;
                }
            """)
        elif state == UIState.SUCCESS:
            self.exec_button.setStyleSheet("""
                QPushButton {
                    background-color: #34C759;
                    color: white;
                    border: none;
                    border-radius: 8px;
                    font-weight: bold;
                }
            """)
            QTimer.singleShot(2000, lambda: self.set_state(UIState.IDLE))
        elif state == UIState.ERROR:
            self.exec_button.setStyleSheet("""
                QPushButton {
                    background-color: #FF3B30;
                    color: white;
                    border: none;
                    border-radius: 8px;
                    font-weight: bold;
                }
            """)


def run_mac_ui():
    """Main entry point for the Mac UI"""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    
    window = FloatingRPAWindow()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_mac_ui()
