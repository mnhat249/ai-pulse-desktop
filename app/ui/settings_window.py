from __future__ import annotations

import logging
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path

import customtkinter as ctk

from app import startup
from app.config import Settings
from app.settings_store import update_settings_file
from app.ui import theme
from app.ui.settings_form import INTERVAL_SOURCES, SettingsDraft

logger = logging.getLogger(__name__)

POLL_MS = 150
ApplyStartup = Callable[[bool], bool]


class SettingsWindow(ctk.CTkToplevel):  # type: ignore[misc]
    """Màn hình cài đặt đơn giản: bật/tắt nguồn, chu kỳ quét, ngưỡng toast, tự khởi động.

    Lưu vào `settings.toml`; thay đổi áp dụng khi mở lại app. Việc tạo/xóa shortcut Startup chạy
    ở luồng riêng để không làm đơ giao diện.
    """

    def __init__(
        self,
        parent: ctk.CTk,
        settings: Settings,
        settings_path: Path,
        fonts: dict[str, ctk.CTkFont],
        apply_startup: ApplyStartup = startup.apply,
    ) -> None:
        super().__init__(parent, fg_color=theme.BG)
        self._settings = settings
        self._path = settings_path
        self._fonts = fonts
        self._apply_startup = apply_startup
        # trạng thái shortcut dùng chung với luồng PowerShell, đọc/ghi dưới `_startup_lock`
        self._startup_lock = threading.Lock()
        self._startup_failures: list[bool] = []
        self._applied_startup = settings.start_with_windows  # trạng thái shortcut đã áp dụng thật
        self._startup_busy = False
        self._startup_pending: bool | None = None  # lần lưu trong lúc PowerShell còn chạy
        self.title("Cài đặt")
        self.geometry("420x640")
        self.attributes("-topmost", True)
        draft = SettingsDraft.from_settings(settings)
        self._enabled = {k: tk.BooleanVar(value=v) for k, v in draft.enabled.items()}
        self._intervals = {k: tk.StringVar(value=v) for k, v in draft.intervals.items()}
        self._importance = tk.StringVar(value=draft.toast_min_importance)
        self._max_per_hour = tk.StringVar(value=draft.toast_max_per_hour)
        self._startup = tk.BooleanVar(value=draft.start_with_windows)
        self._build()

    # ---- giao diện ----------------------------------------------------------------------
    def _section(self, text: str) -> ctk.CTkFrame:
        ctk.CTkLabel(
            self, text=text, font=self._fonts["card_title"], text_color=theme.INK, anchor="w"
        ).pack(fill="x", padx=16, pady=(14, 4))
        card = ctk.CTkFrame(
            self, fg_color=theme.CARD, corner_radius=6, border_width=1, border_color=theme.BORDER
        )
        card.pack(fill="x", padx=12)
        return card

    def _switch(self, parent: ctk.CTkFrame, text: str, var: tk.BooleanVar) -> ctk.CTkSwitch:
        switch = ctk.CTkSwitch(
            parent,
            text=text,
            variable=var,
            font=self._fonts["body"],
            text_color=theme.INK,
            progress_color=theme.SELECTED,
        )
        return switch

    def _entry(self, parent: ctk.CTkFrame, var: tk.StringVar, width: int = 56) -> ctk.CTkEntry:
        return ctk.CTkEntry(
            parent,
            textvariable=var,
            width=width,
            font=self._fonts["body"],
            fg_color=theme.BG,
            border_color=theme.BORDER,
            text_color=theme.INK,
        )

    def _build(self) -> None:
        sources = self._section("Nguồn tin")
        for name, label in INTERVAL_SOURCES.items():
            row = ctk.CTkFrame(sources, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=4)
            self._switch(row, label, self._enabled[name]).pack(side="left")
            ctk.CTkLabel(
                row, text="phút/lần", font=self._fonts["small"], text_color=theme.MUTED
            ).pack(side="right", padx=(4, 0))
            self._entry(row, self._intervals[name]).pack(side="right")
        feeds = [k for k in self._enabled if k.startswith("rss:")]
        if feeds:
            ctk.CTkLabel(
                sources,
                text="Blog và bản tin (RSS)",
                font=self._fonts["lead"],
                text_color=theme.MUTED,
                anchor="w",
            ).pack(fill="x", padx=12, pady=(8, 0))
            for index, key in enumerate(feeds):
                last = index == len(feeds) - 1
                self._switch(sources, key.removeprefix("rss:"), self._enabled[key]).pack(
                    anchor="w", padx=10, pady=(3, 10 if last else 3)
                )

        toasts = self._section("Thông báo")
        for text, var in (
            ("Báo khi tin đạt từ (điểm 0–100)", self._importance),
            ("Tối đa số toast mỗi giờ", self._max_per_hour),
        ):
            row = ctk.CTkFrame(toasts, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=4)
            ctk.CTkLabel(row, text=text, font=self._fonts["body"], text_color=theme.INK).pack(
                side="left"
            )
            self._entry(row, var).pack(side="right")

        system = self._section("Hệ thống")
        self._switch(system, "Tự khởi động cùng Windows", self._startup).pack(
            anchor="w", padx=10, pady=8
        )

        self._message = ctk.CTkLabel(
            self,
            text="Thay đổi áp dụng sau khi mở lại NeuralRadar.",
            font=self._fonts["small"],
            text_color=theme.MUTED,
            wraplength=380,
            justify="left",
            anchor="w",
        )
        self._message.pack(fill="x", padx=16, pady=(12, 4))
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=12, pady=8)
        for text, command, filled in (("Lưu", self.save, True), ("Đóng", self.destroy, False)):
            ctk.CTkButton(
                buttons,
                text=text,
                command=command,
                width=84,
                height=28,
                corner_radius=6,
                font=self._fonts["body"],
                fg_color=theme.INK if filled else "transparent",
                hover_color="#1E4552" if filled else theme.TRACK,
                text_color="#FFFFFF" if filled else theme.INK,
                border_width=0 if filled else 1,
                border_color=theme.BORDER,
            ).pack(side="left", padx=(0, 6))

    # ---- lưu ----------------------------------------------------------------------------
    def collect(self) -> SettingsDraft:
        return SettingsDraft(
            enabled={k: v.get() for k, v in self._enabled.items()},
            intervals={k: v.get() for k, v in self._intervals.items()},
            toast_min_importance=self._importance.get(),
            toast_max_per_hour=self._max_per_hour.get(),
            start_with_windows=self._startup.get(),
        )

    def save(self) -> bool:
        draft = self.collect()
        problems = draft.errors()
        if problems:
            self._message.configure(text="\n".join(problems), text_color=theme.ERROR)
            return False
        try:
            update_settings_file(self._path, draft.to_updates(self._settings))
        except (OSError, ValueError):  # ValueError: settings.toml hiện có bị hỏng, không đọc được
            logger.exception("Không ghi được settings.toml")
            self._message.configure(
                text="Không ghi được file cài đặt (file có thể đang hỏng).", text_color=theme.ERROR
            )
            return False
        self._message.configure(text="Đã lưu. Mở lại NeuralRadar để áp dụng.", text_color=theme.INK)
        self._request_startup(draft.start_with_windows)
        return True

    def _request_startup(self, enabled: bool) -> None:
        """PowerShell mất khoảng một giây: chạy ở luồng riêng, giao diện chỉ hỏi kết quả."""
        with self._startup_lock:
            if self._startup_busy:  # mỗi lúc chỉ một luồng; luồng đó tự áp dụng giá trị mới nhất
                self._startup_pending = enabled
                return
            if enabled == self._applied_startup:
                return
            self._startup_busy = True
        threading.Thread(
            target=self._startup_worker, args=(enabled,), name="startup-shortcut", daemon=True
        ).start()
        self.after(POLL_MS, self._poll_startup)

    def _startup_worker(self, enabled: bool) -> None:
        """Áp dụng tới khi hết lần lưu đang chờ, kể cả khi cửa sổ đã đóng giữa chừng."""
        while True:
            ok = self._apply_startup(enabled)
            with self._startup_lock:
                if ok:
                    self._applied_startup = enabled  # lần lưu sau so với trạng thái mới này
                else:
                    self._startup_failures.append(enabled)
                pending, self._startup_pending = self._startup_pending, None
                if pending is None or pending == self._applied_startup:
                    self._startup_busy = False
                    return
            enabled = pending

    def _poll_startup(self) -> None:
        if not self.winfo_exists():  # cửa sổ đã đóng trong lúc chờ
            return
        with self._startup_lock:
            busy = self._startup_busy
            failed = bool(self._startup_failures)
            self._startup_failures.clear()
        if failed:
            self._message.configure(
                text="Đã lưu, nhưng không tạo/xóa được shortcut khởi động cùng Windows.",
                text_color=theme.ERROR,
            )
        if busy:
            self.after(POLL_MS, self._poll_startup)
