from __future__ import annotations

import logging
import queue
import webbrowser
from pathlib import Path
from typing import Protocol

import customtkinter as ctk

from app.config import Settings, app_home
from app.core import sources
from app.storage.ui_queries import ClusterView, source_label
from app.ui import theme
from app.ui import tray as tray_commands
from app.ui.backend import UIEvent
from app.ui.model import FILTER_LABELS, UIModel
from app.ui.notifier import Notifier
from app.ui.settings_window import SettingsWindow
from app.ui.state import WindowState, load_state, save_state
from app.ui.tray import Tray

logger = logging.getLogger(__name__)

POLL_MS = 500
SAVE_DEBOUNCE_MS = 600
WRAP = 318
STRIP_WIDTH = 6
CARD_RADIUS = 6


class Controller(Protocol):
    """Những gì widget được phép nhờ luồng nền làm; mọi hàm đều không chặn."""

    def run_now(self) -> None: ...
    def pause(self) -> None: ...
    def resume(self) -> None: ...
    def mark_read(self, cluster_id: int, read: bool = True) -> None: ...
    def set_bookmark(self, cluster_id: int, bookmarked: bool) -> None: ...


def open_link(url: str | None) -> bool:
    """Chỉ mở http(s); không bao giờ mở file:// hay lệnh lạ."""
    if url and url.startswith(("http://", "https://")):
        webbrowser.open(url)
        return True
    return False


class FloatingWidget(ctk.CTk):  # type: ignore[misc]
    """Widget nổi. Không gọi mạng, không chờ I/O dài: chỉ đọc DB nhanh bằng kết nối riêng."""

    def __init__(
        self,
        settings: Settings,
        model: UIModel,
        controller: Controller,
        events: queue.Queue[UIEvent],
        commands: queue.SimpleQueue[str],
        notifier: Notifier | None,
        state_path: Path,
        tray: Tray | None = None,
        settings_path: Path | None = None,
    ) -> None:
        super().__init__()
        self._settings_path = settings_path or app_home() / "settings.toml"
        self._settings = settings
        self._model = model
        self._controller = controller
        self._events = events
        self._commands = commands
        self._notifier = notifier
        self._state_path = state_path
        self._tray = tray
        self._tray_ok = False
        self._paused = False
        self._closed = False
        self._save_job: str | None = None
        self.quit_requested = False
        self._state = load_state(state_path, settings.ui.always_on_top)

        ctk.set_appearance_mode("light")
        self.title("NeuralRadar")
        self.configure(fg_color=theme.BG)
        self.minsize(320, 300)
        self.geometry(self._state.geometry)
        self.attributes("-topmost", self._state.always_on_top)
        self.attributes("-alpha", 0.97)
        display = theme.pick_family(theme.DISPLAY_FONTS)
        body = theme.pick_family(theme.BODY_FONTS)
        self._fonts = {
            "title": ctk.CTkFont(family=display, size=20),
            "card_title": ctk.CTkFont(family=body, size=14, weight="bold"),
            "card_title_read": ctk.CTkFont(family=body, size=14),
            "body": ctk.CTkFont(family=body, size=13),
            "lead": ctk.CTkFont(family=display, size=12),
            "small": ctk.CTkFont(family=body, size=11),
            "chip": ctk.CTkFont(family=body, size=11, weight="bold"),
        }
        self._model.set_topic_label(self._state.topic or self._model.topic)
        self._build()
        self.bind("<Configure>", self._on_configure)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.refresh()

    @property
    def paused(self) -> bool:
        return self._paused

    # ---- dựng giao diện -------------------------------------------------------------------
    def _button(
        self,
        parent: ctk.CTkBaseClass,
        text: str,
        command: object,
        *,
        filled: bool,
        width: int = 84,
    ) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            font=self._fonts["body"],
            width=width,
            height=28,
            corner_radius=CARD_RADIUS,
            fg_color=theme.INK if filled else "transparent",
            hover_color="#1E4552" if filled else theme.TRACK,
            text_color="#FFFFFF" if filled else theme.INK,
            border_width=0 if filled else 1,
            border_color=theme.BORDER,
        )

    def _build(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(12, 2))
        ctk.CTkLabel(
            header, text="NeuralRadar", font=self._fonts["title"], text_color=theme.INK
        ).pack(side="left")
        self._button(header, "Nguồn", self.show_statuses, filled=False, width=64).pack(side="right")
        self._top_button = self._button(
            header, "", self.toggle_always_on_top, filled=False, width=68
        )
        self._top_button.pack(side="right", padx=6)
        self._button(header, "Chạy ngay", self.run_now, filled=True, width=88).pack(side="right")

        info_row = ctk.CTkFrame(self, fg_color="transparent")
        info_row.pack(fill="x", padx=14)
        self._unread_label = ctk.CTkLabel(
            info_row, text="", font=self._fonts["body"], text_color=theme.MUTED, anchor="w"
        )
        self._unread_label.pack(side="left")
        self._button(info_row, "Cài đặt", self.show_settings, filled=False, width=70).pack(
            side="right"
        )

        filters = ctk.CTkFrame(self, fg_color="transparent")
        filters.pack(fill="x", padx=12, pady=6)
        self._filter_button = ctk.CTkSegmentedButton(
            filters,
            values=list(FILTER_LABELS),
            command=self._on_filter,
            font=self._fonts["body"],
            fg_color=theme.CARD,
            selected_color=theme.SELECTED,
            selected_hover_color=theme.SELECTED,
            unselected_color=theme.CARD,
            unselected_hover_color=theme.TRACK,
            text_color=theme.INK,
            text_color_disabled=theme.MUTED,
        )
        self._filter_button.set("Tất cả")
        self._filter_button.pack(side="left")
        self._source_menu = ctk.CTkOptionMenu(
            filters,
            values=self._model.source_choices(),
            command=self._on_source,
            width=112,
            font=self._fonts["body"],
            dropdown_font=self._fonts["body"],
            fg_color=theme.CARD,
            button_color=theme.TRACK,
            button_hover_color=theme.BORDER,
            text_color=theme.INK,
            dropdown_fg_color=theme.CARD,
            dropdown_text_color=theme.INK,
        )
        self._source_menu.pack(side="right")

        topic_row = ctk.CTkFrame(self, fg_color="transparent")
        topic_row.pack(fill="x", padx=12, pady=(0, 4))
        ctk.CTkLabel(
            topic_row, text="Chủ đề", font=self._fonts["body"], text_color=theme.MUTED
        ).pack(side="left", padx=(2, 6))
        self._topic_menu = ctk.CTkOptionMenu(
            topic_row,
            values=self._model.topic_choices(),
            command=self._on_topic,
            width=170,
            font=self._fonts["body"],
            dropdown_font=self._fonts["body"],
            fg_color=theme.CARD,
            button_color=theme.TRACK,
            button_hover_color=theme.BORDER,
            text_color=theme.INK,
            dropdown_fg_color=theme.CARD,
            dropdown_text_color=theme.INK,
        )
        self._topic_menu.set(self._model.topic)
        self._topic_menu.pack(side="left")

        self._status_label = ctk.CTkLabel(
            self, text="", font=self._fonts["small"], text_color=theme.MUTED, anchor="w", height=14
        )
        self._status_label.pack(fill="x", padx=14)
        self._feed = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._feed.pack(fill="both", expand=True, padx=6, pady=(2, 8))
        self._update_top_button()

    def _update_top_button(self) -> None:
        self._top_button.configure(text="Ghim ✓" if self._state.always_on_top else "Ghim")

    # ---- vòng lặp chính -------------------------------------------------------------------
    def start_polling(self) -> None:
        self.after(POLL_MS, self._drain)

    def run(self) -> None:
        self.start_polling()
        self.mainloop()

    def _drain(self) -> None:
        """Mỗi 500ms đọc lệnh từ khay và sự kiện từ luồng nền. Luôn đặt lịch lại, kể cả khi lỗi."""
        try:
            self.process_commands()
            self.process_events()
        except Exception:
            logger.exception("Lỗi khi cập nhật giao diện")
        finally:
            if not self._closed:
                self.after(POLL_MS, self._drain)

    def process_commands(self) -> None:
        while not self._commands.empty():
            command = self._commands.get_nowait()
            if command == tray_commands.QUIT:
                self.quit_requested = True
                self.shutdown()
                return
            if command == tray_commands.TOGGLE:
                self.toggle_visibility()
            elif command == tray_commands.SHOW:
                self.show_window()
            elif command == tray_commands.RUN_NOW:
                self.run_now()
            elif command == tray_commands.PAUSE:
                self.set_paused(True)
            elif command == tray_commands.RESUME:
                self.set_paused(False)

    def process_events(self) -> None:
        changed: list[int] = []
        got_event = False
        while True:
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                break
            got_event = True
            if event.kind == "updated":  # chỉ tin mới xử lý xong mới được xét toast
                changed.extend(event.cluster_ids)
        if not got_event:
            return
        if not self._paused:
            self._status_label.configure(text="")
        self.refresh()
        self._toast(dict.fromkeys(changed))

    def _toast(self, cluster_ids: dict[int, None]) -> None:
        if self._notifier is None:
            return
        for cluster_id in cluster_ids:
            view = self._model.cluster(cluster_id)
            if view is not None:
                self._notifier.notify(view)

    # ---- hành động ------------------------------------------------------------------------
    def show_window(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()

    def toggle_visibility(self) -> None:
        if self.state() == "withdrawn":
            self.show_window()
        else:
            self.withdraw()

    def run_now(self) -> None:
        self._status_label.configure(text="Đang quét các nguồn…")
        self._controller.run_now()

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        (self._controller.pause if paused else self._controller.resume)()
        self._status_label.configure(text="Đã tạm dừng thu thập" if paused else "")
        if self._tray is not None:
            self._tray.update()

    def toggle_always_on_top(self) -> None:
        self._state.always_on_top = not self._state.always_on_top
        self.attributes("-topmost", self._state.always_on_top)
        self._update_top_button()
        self._save_now()

    def _on_filter(self, label: str) -> None:
        self._model.set_filter_label(label)
        self.refresh()

    def _on_source(self, label: str) -> None:
        self._model.set_source_label(label)
        self.refresh()

    def _on_topic(self, label: str) -> None:
        self._model.set_topic_label(label)
        self._state.topic = self._model.topic
        self._save_now()
        self.refresh()

    def open_cluster_link(self, cluster: ClusterView) -> None:
        if open_link(cluster.primary_url):
            if not cluster.read:
                self._controller.mark_read(cluster.id)

    def toggle_read(self, cluster: ClusterView) -> None:
        self._controller.mark_read(cluster.id, not cluster.read)

    def toggle_bookmark(self, cluster: ClusterView) -> None:
        self._controller.set_bookmark(cluster.id, not cluster.bookmarked)

    def toggle_card(self, cluster_id: int) -> None:
        self._model.toggle_expanded(cluster_id)
        self.refresh()

    # ---- hiển thị -------------------------------------------------------------------------
    def refresh(self) -> None:
        for child in self._feed.winfo_children():
            child.destroy()
        clusters = self._model.clusters()
        unread = self._model.unread_count()
        self._unread_label.configure(text=f"{unread} tin chưa đọc" if unread else "Đã đọc hết")
        self._source_menu.configure(values=self._model.source_choices())
        if not clusters:
            ctk.CTkLabel(
                self._feed,
                text="Chưa có tin nào khớp.\nĐổi bộ lọc hoặc bấm Chạy ngay để quét lại.",
                font=self._fonts["body"],
                text_color=theme.MUTED,
                justify="left",
            ).pack(pady=24, padx=8, anchor="w")
        for cluster in clusters:
            self._add_card(cluster)

    def _signal_strip(self, parent: ctk.CTkFrame, cluster: ClusterView) -> None:
        """Dải tín hiệu: chiều cao lấp đầy theo điểm quan trọng; đã đọc thì chỉ còn màu mờ."""
        track = ctk.CTkFrame(
            parent, width=STRIP_WIDTH, height=1, corner_radius=3, fg_color=theme.TRACK
        )
        track.pack(side="left", fill="y", padx=(8, 0), pady=8)
        track.pack_propagate(False)
        color = theme.TRACK if cluster.read else theme.signal_color(cluster.importance)
        fill = ctk.CTkFrame(track, width=STRIP_WIDTH, height=1, corner_radius=3, fg_color=color)
        fill.place(
            relx=0,
            rely=1.0,
            relwidth=1.0,
            relheight=theme.signal_fill(cluster.importance),
            anchor="sw",
        )

    def _chip(self, parent: ctk.CTkFrame, text: str, color: str) -> None:
        ctk.CTkLabel(
            parent,
            text=text,
            font=self._fonts["chip"],
            text_color="#FFFFFF",
            fg_color=color,
            corner_radius=4,
            height=18,
        ).pack(side="left", padx=(0, 4))

    def _add_card(self, cluster: ClusterView) -> None:
        expanded = cluster.id in self._model.expanded
        card = ctk.CTkFrame(
            self._feed,
            corner_radius=CARD_RADIUS,
            fg_color=theme.CARD,
            border_width=1,
            border_color=theme.BORDER,
        )
        card.pack(fill="x", pady=3, padx=6)
        self._signal_strip(card, cluster)
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(side="left", fill="both", expand=True, padx=(8, 10), pady=8)

        star = "  ★" if cluster.bookmarked else ""
        title = ctk.CTkLabel(
            body,
            text=f"{cluster.title}{star}",
            wraplength=WRAP,
            anchor="w",
            justify="left",
            font=self._fonts["card_title_read" if cluster.read else "card_title"],
            text_color=theme.MUTED if cluster.read else theme.INK,
        )
        title.pack(fill="x")

        meta = ctk.CTkFrame(body, fg_color="transparent")
        meta.pack(fill="x", pady=(4, 0))
        for source in cluster.sources:
            self._chip(meta, source_label(source), theme.source_color(source))
        if not cluster.summarized:
            self._chip(meta, "Chờ tóm tắt", theme.MUTED)
        ctk.CTkLabel(
            meta,
            text=theme.relative_time(cluster.last_seen),
            font=self._fonts["small"],
            text_color=theme.MUTED,
        ).pack(side="right")

        for widget in (card, body, title, meta):
            widget.bind("<Button-1>", lambda _e, cid=cluster.id: self.toggle_card(cid))
        if not expanded:
            return

        if cluster.summarized:
            for lead, text in (("Cái mới", cluster.innovation), ("Dùng để", cluster.impact)):
                row = ctk.CTkFrame(body, fg_color="transparent")
                row.pack(fill="x", pady=(8, 0))
                ctk.CTkLabel(
                    row,
                    text=lead,
                    font=self._fonts["lead"],
                    text_color=theme.MUTED,
                    anchor="w",
                    height=16,
                ).pack(fill="x")
                ctk.CTkLabel(
                    row,
                    height=0,
                    text=text or "",
                    font=self._fonts["body"],
                    text_color=theme.INK,
                    wraplength=WRAP,
                    anchor="w",
                    justify="left",
                ).pack(fill="x")
        ctk.CTkLabel(
            body,
            text=f"Quan trọng {cluster.importance:.0f}/100",
            font=self._fonts["small"],
            text_color=theme.MUTED,
            anchor="w",
        ).pack(fill="x", pady=(8, 0))
        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.pack(fill="x", pady=(8, 0))
        self._button(
            buttons, "Mở link", lambda c=cluster: self.open_cluster_link(c), filled=True
        ).pack(side="left")
        self._button(
            buttons,
            "Bỏ bookmark" if cluster.bookmarked else "Bookmark",
            lambda c=cluster: self.toggle_bookmark(c),
            filled=False,
        ).pack(side="left", padx=6)
        self._button(
            buttons,
            "Chưa đọc" if cluster.read else "Đã đọc",
            lambda c=cluster: self.toggle_read(c),
            filled=False,
        ).pack(side="left")

    def show_settings(self) -> None:
        """Mở màn hình cài đặt (ghi settings.toml; áp dụng khi mở lại app)."""
        SettingsWindow(self, self._settings, self._settings_path, self._fonts)

    def show_statuses(self) -> None:
        """Màn hình "tình trạng nguồn": lần chạy cuối và lỗi gần nhất của từng nguồn."""
        window = ctk.CTkToplevel(self, fg_color=theme.BG)
        window.title("Tình trạng nguồn")
        window.geometry("440x460")
        window.attributes("-topmost", True)
        body = ctk.CTkScrollableFrame(window, fg_color=theme.BG)
        body.pack(fill="both", expand=True)
        statuses = self._model.statuses()
        if not statuses:
            ctk.CTkLabel(
                body,
                text="Chưa có lần quét nào. Bấm Chạy ngay để quét.",
                font=self._fonts["body"],
                text_color=theme.MUTED,
            ).pack(pady=20)
        for status in statuses:
            frame = ctk.CTkFrame(
                body,
                fg_color=theme.CARD,
                corner_radius=CARD_RADIUS,
                border_width=1,
                border_color=theme.BORDER,
            )
            frame.pack(fill="x", padx=6, pady=4)
            mark = "✓" if status.ok else "✗"
            name = sources.display_name(status.source)
            line = f"{mark} {name} — {theme.relative_time(status.last_run)}"
            ctk.CTkLabel(
                frame,
                text=f"{line} — {status.item_count} bài",
                anchor="w",
                font=self._fonts["card_title"],
                text_color=theme.INK if status.ok else theme.ERROR,
            ).pack(fill="x", padx=10, pady=(8, 0))
            error = status.error if not status.ok else self._model.last_error(status.source)
            if error:
                ctk.CTkLabel(
                    frame,
                    text=f"Lỗi gần nhất: {error}",
                    text_color=theme.ERROR if not status.ok else theme.MUTED,
                    font=self._fonts["small"],
                    wraplength=380,
                    anchor="w",
                    justify="left",
                ).pack(fill="x", padx=10, pady=(0, 8))
            else:
                ctk.CTkFrame(frame, height=6, fg_color="transparent").pack()

    # ---- lưu trạng thái và thoát ----------------------------------------------------------
    def _on_configure(self, event: object) -> None:
        if getattr(event, "widget", None) is not self:
            return
        if self._save_job is not None:
            self.after_cancel(self._save_job)
        self._save_job = self.after(SAVE_DEBOUNCE_MS, self._save_now)

    def _save_now(self) -> None:
        self._save_job = None
        if self.state() == "withdrawn" or self._closed:
            save_state(self._state_path, self._state)
            return
        self._state = WindowState(
            x=self.winfo_x(),
            y=self.winfo_y(),
            width=round(self.winfo_width() / self._get_window_scaling()),
            height=round(self.winfo_height() / self._get_window_scaling()),
            always_on_top=self._state.always_on_top,
            topic=self._state.topic,
        )
        save_state(self._state_path, self._state)

    def mark_tray_ready(self) -> None:
        self._tray_ok = True

    def _on_close(self) -> None:
        """Bấm X: có khay thì chỉ ẩn; không có khay thì thoát để khỏi mất đường ra."""
        if self._tray_ok:
            self._save_now()
            self.withdraw()
        else:
            self.quit_requested = True
            self.shutdown()

    def shutdown(self) -> None:
        if self._closed:
            return
        self._save_now()
        self._closed = True
        self.destroy()
