"""DearPyGUI presentation layer for Clean Arch."""

from __future__ import annotations

import os
import sys
import time

import dearpygui.dearpygui as dpg

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from clean_arch.application.log_policy import classify  # noqa: E402
from clean_arch.domain.models import SessionMode, SessionSettings  # noqa: E402
from clean_arch.infrastructure.configuration import load_credentials  # noqa: E402
from clean_arch.infrastructure.process_controller import WorkerProcess  # noqa: E402


ROOT = HERE
DEFAULT_CONFIG = os.path.join(ROOT, "console_client_config.txt")
WORKER = os.path.join(HERE, "worker_entry.py")
ACCOUNTS_DIR = os.path.join(ROOT, "accounts")
AUTO_CLOSE_DELAY = 3 * 60 * 60
AUTO_CLOSE_WARNING = 60.0
WORKER_RUN_SECONDS = 50.0
MIN_COOLDOWN = 0.1
DEFAULT_COOLDOWN = 4.0
MAX_LOG_LINES = 800
COPY_LOG_LINES = 100
COPY_LOG_HISTORY = 300

COLORS = {
    "default": [221, 221, 221],
    "success": [102, 187, 106],
    "error": [239, 83, 80],
    "pending": [198, 40, 40],
    "ok": [46, 125, 50],
    "muted": [150, 150, 150],
}


class AccountTab:
    def __init__(self, app: "GuiApp", path: str, login: str,
                 mode: SessionMode):
        self.app = app
        self.path = path
        self.login = login
        self.mode = mode
        self.manual_stop = False
        self.finished = False
        self.expired = False
        self.deadline: float | None = None
        self.cooldown = DEFAULT_COOLDOWN
        self.history: list[str] = []
        self.quest_items: list[int | str] = []
        self.connection_items: list[int | str] = []
        self.process = WorkerProcess(WORKER, HERE)
        self.tag = dpg.generate_uuid()
        with dpg.tab(parent=app.tab_bar, label=login, tag=self.tag):
            with dpg.group(horizontal=True):
                dpg.add_text(f"Логін: {login}")
                dpg.add_text(os.path.basename(path), color=COLORS["muted"])
                self.pending = dpg.add_text("Очікування: перевірка квесту 17064...",
                                            color=COLORS["muted"])
                dpg.add_text(" Квест здано:", color=COLORS["muted"])
                self.return_status = dpg.add_text("очікується", color=COLORS["pending"])
                dpg.add_text(" Квест прийнято:", color=COLORS["muted"])
                self.accept_status = dpg.add_text("очікується", color=COLORS["pending"])
                dpg.add_button(label="Reconnect", callback=self.reconnect)
                self.auto_reconnect = dpg.add_checkbox(label="Auto reconnect",
                                                        default_value=True)
                dpg.add_button(label="Disconnect", callback=self.disconnect)
                dpg.add_button(label="Copy log (last 100)", callback=self.copy_log)
                dpg.add_button(label="Закрити вкладку",
                               callback=app.close_tab, user_data=self.tag)
            with dpg.group(horizontal=True):
                dpg.add_text("Квести / NPC", color=COLORS["muted"])
                dpg.add_spacer(width=300)
                dpg.add_text("Підключення / KeepAlive", color=COLORS["muted"])
            with dpg.group(horizontal=True):
                self.quest_window = dpg.add_child_window(width=480, height=-1,
                                                         border=False)
                self.connection_window = dpg.add_child_window(width=-1, height=-1,
                                                              border=False)
            with dpg.group(horizontal=True):
                dpg.add_text("Cooldown:", color=COLORS["muted"])
                self.cooldown_input = dpg.add_input_float(
                    default_value=DEFAULT_COOLDOWN, min_value=MIN_COOLDOWN,
                    min_clamped=True, width=100, callback=self.set_cooldown)
        self.start()

    def start(self) -> None:
        active = self.app.active_tab
        if active is not None and active is not self and not active.expired:
            self.app.status_text("Зараз працює інша вкладка.", True)
            return
        self.finished = False
        if self.deadline is None:
            self.deadline = time.monotonic() + WORKER_RUN_SECONDS
        self.process.start(SessionSettings(DEFAULT_CONFIG, self.path, self.mode))
        self.process.send_control(f"COOLDOWN {self.cooldown:g}")

    def set_cooldown(self, sender, value: float) -> None:
        self.cooldown = max(MIN_COOLDOWN, float(value))
        if value != self.cooldown:
            dpg.set_value(sender, self.cooldown)
        self.process.send_control(f"COOLDOWN {self.cooldown:g}")

    def drain(self) -> None:
        for event in self.process.poll():
            self.append(event.text)
            if (event.text.startswith("[GUI] Worker exited")
                    or event.text.startswith("[GUI] Worker start failed")):
                self.finish()

    def append(self, text: str) -> None:
        self.history.append(text)
        if len(self.history) > COPY_LOG_HISTORY:
            del self.history[:-COPY_LOG_LINES]
        if "Waiting task" in text and "active; AFK mode" in text:
            dpg.configure_item(self.pending, default_value="Квест у режимі очікування",
                               color=COLORS["ok"])
        elif "Waiting task" in text and "not active" in text:
            dpg.configure_item(self.pending, default_value="Очікування: квест 17064 відсутній",
                               color=COLORS["muted"])
        elif "Could not check waiting task" in text or "Could not decode waiting task" in text:
            dpg.configure_item(self.pending, default_value="Очікування: помилка перевірки",
                               color=COLORS["error"])
        presentation = classify(text)
        actions = presentation.actions
        for action in actions:
            target = self.return_status if action.endswith("return") else self.accept_status
            if action.startswith("ok_"):
                dpg.configure_item(target, default_value="підтверджено", color=COLORS["ok"])
            elif action.startswith("fail_"):
                dpg.configure_item(target, default_value="помилка", color=COLORS["error"])
            elif action.startswith("reset_"):
                dpg.configure_item(target, default_value="очікується", color=COLORS["pending"])
        window = self.quest_window if presentation.pane == "quest" else self.connection_window
        items = self.quest_items if presentation.pane == "quest" else self.connection_items
        items.append(dpg.add_text(text, parent=window, color=COLORS[presentation.color]))
        if len(items) > MAX_LOG_LINES:
            dpg.delete_item(items.pop(0))
        dpg.set_y_scroll(window, -1.0)

    def disconnect(self) -> None:
        self.manual_stop = True
        self.process.stop()

    def reconnect(self, sender=None, app_data=None, user_data=None) -> None:
        self._reconnect(True)

    def _reconnect(self, fresh: bool) -> None:
        self.manual_stop = False
        self.process.stop()
        self.process.clear_events()
        dpg.configure_item(self.return_status, default_value="очікується",
                           color=COLORS["pending"])
        dpg.configure_item(self.accept_status, default_value="очікується",
                           color=COLORS["pending"])
        dpg.configure_item(self.pending,
                           default_value="Очікування: перевірка квесту 17064...",
                           color=COLORS["muted"])
        if fresh:
            self.deadline = None
            self.expired = False
        self.start()

    def finish(self) -> None:
        if self.finished:
            return
        self.finished = True
        if not self.manual_stop and not self.expired and dpg.get_value(self.auto_reconnect):
            self._reconnect(False)

    def copy_log(self) -> None:
        dpg.set_clipboard_text("\n".join(self.history[-COPY_LOG_LINES:]))

    def close(self) -> None:
        self.manual_stop = True
        self.process.stop()
        if dpg.does_item_exist(self.tag):
            dpg.delete_item(self.tag)


class GuiApp:
    def __init__(self):
        self.tabs: dict[int | str, AccountTab] = {}
        self.running = True
        self.auto_queue: list[tuple[str, SessionMode]] = []
        self.active_tab: AccountTab | None = None
        self.close_at = time.monotonic() + AUTO_CLOSE_DELAY
        self.close_warned = False
        dpg.create_context()
        dpg.create_viewport(title="Cyber146 Clean Architecture",
                            width=1100, height=700)
        self._setup_font()
        with dpg.window(tag="main"):
            dpg.add_text("GUI session manager", color=COLORS["muted"])
            dpg.add_button(label="Залогінити аккаунти",
                           callback=lambda: self.show_picker(SessionMode.LOGIN_ONLY))
            with dpg.tab_bar(tag="tabs") as self.tab_bar:
                dpg.add_tab_button(label="+",
                                   callback=lambda: self.show_picker(SessionMode.WORLD))
            self.status = dpg.add_text("Оберіть файли облікових даних.",
                                       color=COLORS["muted"])
        dpg.set_primary_window("main", True)
        self._build_picker()
        self._build_shutdown_dialog()
        self.queue_auto_start()
        self.shift_held = False
        with dpg.handler_registry():
            dpg.add_key_down_handler(
                dpg.mvKey_ModShift,
                callback=lambda: setattr(self, "shift_held", True))
            dpg.add_key_release_handler(
                dpg.mvKey_ModShift,
                callback=lambda: setattr(self, "shift_held", False))
        dpg.set_exit_callback(self.close)
        dpg.setup_dearpygui()
        dpg.show_viewport()
        dpg.set_frame_callback(dpg.get_frame_count() + 1, self.pump)

    def _setup_font(self) -> None:
        for path in (r"C:\Windows\Fonts\segoeui.ttf",
                     r"C:\Windows\Fonts\tahoma.ttf",
                     r"C:\Windows\Fonts\arial.ttf"):
            if not os.path.exists(path):
                continue
            try:
                with dpg.font_registry():
                    font = dpg.add_font(path, 18)
                dpg.bind_font(font)
                return
            except (OSError, RuntimeError):
                continue

    def _build_picker(self) -> None:
        with dpg.window(tag="picker", label="Виберіть credential-файли",
                        modal=True, show=False, width=560, height=520):
            self.folder = dpg.add_input_text(default_value=ROOT, width=-110)
            dpg.add_button(label="Оновити", callback=self.refresh_files)
            self.file_list = dpg.add_child_window(height=-60)
            self.open_button = dpg.add_button(label="Відкрити (0)",
                                              callback=self.open_selected)
            with dpg.group(horizontal=True):
                dpg.add_button(label="Вибрати всі",
                               callback=lambda: self.select_all(True))
                dpg.add_button(label="Зняти все",
                               callback=lambda: self.select_all(False))
                dpg.add_button(label="Скасувати",
                               callback=lambda: dpg.hide_item("picker"))

    def _build_shutdown_dialog(self) -> None:
        with dpg.window(tag="shutdown_dialog", modal=True, show=False,
                        width=470, no_close=True):
            dpg.add_text(
                "Програма закриється через 1 хвилину. "
                "Для того щоб відстрочити закриття на 3 години, "
                "натисніть Окей", wrap=450)
            with dpg.group(horizontal=True):
                dpg.add_spacer(width=350)
                dpg.add_button(label="Окей", callback=self.delay_shutdown)

    def show_picker(self, mode: SessionMode) -> None:
        self.picker_mode = mode
        self.refresh_files()
        dpg.show_item("picker")

    def refresh_files(self) -> None:
        folder = dpg.get_value(self.folder).strip() or ROOT
        try:
            names = sorted((name for name in os.listdir(folder)
                            if name.lower().endswith((".txt", ".cred", ".conf"))),
                           key=str.lower)
        except OSError as error:
            self.status_text(f"Не вдалося прочитати папку: {error}", True)
            names = []
        dpg.delete_item(self.file_list, children_only=True)
        self.paths: list[str] = [os.path.join(folder, name) for name in names]
        self.selected: list[bool] = [False] * len(self.paths)
        self.picker_children: list[int | str] = []
        self.last_selected: int | None = None
        for index, path in enumerate(self.paths):
            self.picker_children.append(dpg.add_checkbox(
                label=os.path.basename(path),
                callback=self.on_picker_toggled,
                user_data=index,
                parent=self.file_list))
        self.update_open_button()

    def on_picker_toggled(self, sender, value: bool, index: int) -> None:
        if value and self.shift_held and self.last_selected is not None:
            start, end = sorted((self.last_selected, index))
            for item_index in range(start, end + 1):
                self.selected[item_index] = True
                dpg.set_value(self.picker_children[item_index], True)
        else:
            self.selected[index] = value
        self.last_selected = index
        self.update_open_button()

    def select_all(self, value: bool) -> None:
        self.selected = [value] * len(self.paths)
        for item, checked in zip(self.picker_children, self.selected):
            dpg.set_value(item, checked)
        self.update_open_button()

    def update_open_button(self) -> None:
        dpg.configure_item(self.open_button, label=f"Відкрити ({sum(self.selected)})")

    def open_account_tab(self, path: str, mode: SessionMode) -> bool:
        try:
            login, _ = load_credentials(path)
        except ValueError as error:
            self.status_text(str(error), True)
            return False
        for tab in self.tabs.values():
            if tab.path == path:
                return False
        tab = AccountTab(self, path, login, mode)
        self.tabs[tab.tag] = tab
        self.active_tab = tab
        return True

    def open_selected(self) -> None:
        queued = 0
        for path, selected in zip(self.paths, self.selected):
            if not selected:
                continue
            if any(tab.path == path for tab in self.tabs.values()):
                continue
            if any(queued_path == path for queued_path, _mode in self.auto_queue):
                continue
            self.auto_queue.append((path, self.picker_mode))
            queued += 1
        if queued == 0:
            self.status_text("Оберіть хоча б один файл.", True)
            return
        dpg.hide_item("picker")
        self.status_text(f"У черзі: {queued}. Працює одна вкладка за раз, {WORKER_RUN_SECONDS:g} с.")

    def queue_auto_start(self) -> None:
        try:
            names = sorted((name for name in os.listdir(ACCOUNTS_DIR)
                            if name.lower().endswith((".txt", ".cred", ".conf"))),
                           key=str.lower)
        except OSError:
            return
        self.auto_queue = [(os.path.join(ACCOUNTS_DIR, name), SessionMode.WORLD)
                           for name in names]
        if self.auto_queue:
            self.status_text(f"Автозапуск: знайдено файлів: {len(self.auto_queue)}")

    def _tab_running(self, tab: AccountTab) -> bool:
        process = tab.process.process
        return process is not None and process.poll() is None

    def pump_auto_start(self) -> None:
        now = time.monotonic()
        active = self.active_tab
        if active is not None:
            if active.deadline is not None and now >= active.deadline:
                if not active.expired:
                    active.expired = True
                    active.manual_stop = True
                    active.process.stop()
                self.active_tab = None
            elif not self._tab_running(active) and (active.manual_stop or active.finished or active.expired):
                self.active_tab = None
            else:
                return
        while self.auto_queue:
            path, mode = self.auto_queue.pop(0)
            if self.open_account_tab(path, mode):
                self.status_text(f"Запущено: {os.path.basename(path)} "
                                 f"({WORKER_RUN_SECONDS:g} с, у черзі: {len(self.auto_queue)})")
                return

    def status_text(self, text: str, bad: bool = False) -> None:
        dpg.configure_item(self.status, default_value=text,
                           color=COLORS["error"] if bad else COLORS["muted"])

    def close_tab(self, sender, app_data, user_data) -> None:
        tab = self.tabs.pop(user_data, None)
        if tab:
            if self.active_tab is tab:
                self.active_tab = None
            tab.close()

    def delay_shutdown(self) -> None:
        self.close_at = time.monotonic() + AUTO_CLOSE_DELAY
        self.close_warned = False
        dpg.hide_item("shutdown_dialog")

    def check_shutdown(self) -> None:
        now = time.monotonic()
        if now >= self.close_at:
            self.close()
            dpg.stop_dearpygui()
            return
        if not self.close_warned and now >= self.close_at - AUTO_CLOSE_WARNING:
            self.close_warned = True
            dpg.show_item("shutdown_dialog")

    def pump(self) -> None:
        if not self.running:
            return
        for tab in list(self.tabs.values()):
            tab.drain()
        self.pump_auto_start()
        self.check_shutdown()
        dpg.set_frame_callback(dpg.get_frame_count() + 1, self.pump)

    def close(self) -> None:
        self.running = False
        for tab in list(self.tabs.values()):
            tab.close()


def main() -> int:
    app = GuiApp()
    try:
        dpg.start_dearpygui()
    finally:
        app.close()
        dpg.destroy_context()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
