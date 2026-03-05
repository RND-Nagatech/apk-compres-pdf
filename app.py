import os
import platform
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import logging
from datetime import datetime
from pathlib import Path

import customtkinter as ctk
from tkinter import filedialog, messagebox
from tkinterdnd2 import DND_FILES, TkinterDnD


COMPRESSION_MAP = {
    "Low": "/screen",
    "Medium": "/ebook",
    "High": "/printer",
}


class DnDCTk(ctk.CTk, TkinterDnD.DnDWrapper):
    """CustomTkinter window with tkinterdnd2 support."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.TkdndVersion = TkinterDnD._require(self)


class App(DnDCTk):
    """Desktop application for PDF compression using Ghostscript."""

    def __init__(self) -> None:
        super().__init__()
        self.title("CompressPDF")
        self.geometry("1180x760")
        self.minsize(1040, 680)

        ctk.set_default_color_theme("green")
        ctk.set_appearance_mode("dark")
        ctk.set_widget_scaling(0.9)

        self.selected_files: list[str] = []
        self.compression_level = "Low"
        self.is_processing = False
        self.queue: queue.Queue = queue.Queue()
        self.is_drag_active = False
        self.drag_animation_job = None
        self.drag_animation_step = 0
        self.preview_scroll_hover = False
        self.preview_layout_job = None
        self.preview_scrollbar_widget = None
        self.queue_poll_job = None
        self.perf_monitor_job = None
        self._perf_last_tick = None
        self.perf_logger: logging.Logger | None = None
        self.gs_path: str | None = None

        self.total_saved_bytes = 0
        self.total_processed = 0
        self.total_elapsed_seconds = 0.0

        self.output_folder = Path.home() / "Documents" / "Compressed_PDFs"
        self.output_folder.mkdir(parents=True, exist_ok=True)
        self._setup_performance_logger()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_ui()
        self.queue_poll_job = self.after(120, self._process_queue)
        self._start_perf_monitor()

    def _setup_performance_logger(self) -> None:
        """Create file logger for tracing UI responsiveness issues."""
        try:
            log_file = self.output_folder / "app_performance.log"
            logger = logging.getLogger("compresspdf.perf")
            logger.setLevel(logging.INFO)

            # avoid duplicate handlers when app re-instantiated in tests
            if not logger.handlers:
                handler = logging.FileHandler(log_file, encoding="utf-8")
                handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
                logger.addHandler(handler)

            self.perf_logger = logger
            self._log_perf("Performance logger initialized")
        except Exception:
            self.perf_logger = None

    def _log_perf(self, message: str) -> None:
        try:
            if self.perf_logger is not None:
                self.perf_logger.info(message)
        except Exception:
            pass

    def _start_perf_monitor(self) -> None:
        self._perf_last_tick = time.perf_counter()
        self.perf_monitor_job = self.after(250, self._monitor_event_loop)

    def _monitor_event_loop(self) -> None:
        """Track event-loop jitter to detect UI stalls/delays."""
        now = time.perf_counter()
        if self._perf_last_tick is not None:
            elapsed_ms = (now - self._perf_last_tick) * 1000
            # expected ~250ms, warn when main thread stalls significantly
            if elapsed_ms > 420:
                self._log_perf(f"Event loop jitter detected: {elapsed_ms:.1f} ms")

        self._perf_last_tick = now
        self.perf_monitor_job = self.after(250, self._monitor_event_loop)

    def _on_close(self) -> None:
        try:
            if self.drag_animation_job is not None:
                self.after_cancel(self.drag_animation_job)
                self.drag_animation_job = None
        except Exception:
            pass

        try:
            if self.preview_layout_job is not None:
                self.after_cancel(self.preview_layout_job)
                self.preview_layout_job = None
        except Exception:
            pass

        try:
            if self.queue_poll_job is not None:
                self.after_cancel(self.queue_poll_job)
                self.queue_poll_job = None
        except Exception:
            pass

        try:
            if self.perf_monitor_job is not None:
                self.after_cancel(self.perf_monitor_job)
                self.perf_monitor_job = None
        except Exception:
            pass

        self._log_perf("Application closing")

        self.destroy()

    @staticmethod
    def _button_palette(variant: str) -> dict[str, str | int]:
        palettes = {
            "primary": {
                "fg_color": "#97eb30",
                "hover_color": "#83d427",
                "pressed_color": "#75bf24",
                "text_color": "#10213e",
                "corner_radius": 10,
            },
            "secondary": {
                "fg_color": "#1b3158",
                "hover_color": "#25406f",
                "pressed_color": "#152a4a",
                "text_color": "#d7e4ff",
                "corner_radius": 10,
            },
            "outline": {
                "fg_color": "transparent",
                "hover_color": "#1f345b",
                "pressed_color": "#1a2f53",
                "text_color": "#88e53a",
                "corner_radius": 8,
            },
            "ghost": {
                "fg_color": "transparent",
                "hover_color": "#20385f",
                "pressed_color": "#1a2f53",
                "text_color": "#96a9cd",
                "corner_radius": 10,
            },
        }
        return palettes.get(variant, palettes["primary"])

    def _create_styled_button(
        self,
        master,
        text: str,
        command,
        variant: str = "primary",
        **kwargs,
    ) -> ctk.CTkButton:
        palette = self._button_palette(variant)
        def wrapped_command():
            started = time.perf_counter()
            try:
                command()
            finally:
                elapsed_ms = (time.perf_counter() - started) * 1000
                if elapsed_ms >= 8:
                    self._log_perf(f"Button '{text}' command took {elapsed_ms:.1f} ms")

        button = ctk.CTkButton(
            master,
            text=text,
            command=wrapped_command,
            fg_color=palette["fg_color"],
            hover_color=palette["hover_color"],
            text_color=palette["text_color"],
            corner_radius=palette["corner_radius"],
            **kwargs,
        )
        try:
            button.configure(cursor="hand2")
        except Exception:
            pass

        button._normal_color = palette["fg_color"]
        button._pressed_color = palette["pressed_color"]

        button.bind("<ButtonPress-1>", lambda _e, b=button: self._on_button_press_feedback(b), add="+")
        button.bind("<ButtonRelease-1>", lambda _e, b=button: self._on_button_release_feedback(b), add="+")
        button.bind("<Leave>", lambda _e, b=button: self._on_button_leave_feedback(b), add="+")
        return button

    @staticmethod
    def _on_button_press_feedback(button: ctk.CTkButton) -> None:
        try:
            if button.cget("state") == "disabled":
                return
            button.configure(fg_color=button._pressed_color)
        except Exception:
            pass

    @staticmethod
    def _on_button_release_feedback(button: ctk.CTkButton) -> None:
        try:
            if button.cget("state") == "disabled":
                return
            button.configure(fg_color=button._normal_color)
        except Exception:
            pass

    @staticmethod
    def _on_button_leave_feedback(button: ctk.CTkButton) -> None:
        try:
            if button.cget("state") == "disabled":
                return
            button.configure(fg_color=button._normal_color)
        except Exception:
            pass

    def _set_compress_button_busy(self, is_busy: bool) -> None:
        if not hasattr(self, "compress_btn"):
            return

        if is_busy:
            self.compress_btn.configure(
                state="disabled",
                fg_color="#5b6475",
                text_color="#d3d8e3",
                hover=False,
            )
            try:
                self.compress_btn.configure(cursor="arrow")
            except Exception:
                pass
            return

        normal_color = getattr(self.compress_btn, "_normal_color", "#97eb30")
        self.compress_btn.configure(
            state="normal",
            fg_color=normal_color,
            text_color="#10213e",
            hover=True,
        )
        try:
            self.compress_btn.configure(cursor="hand2")
        except Exception:
            pass

    def _build_ui(self) -> None:
        self.configure(fg_color="#071634")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, corner_radius=0, fg_color="#0b1c3f", height=60)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        header.grid_columnconfigure(1, weight=0)

        brand = ctk.CTkFrame(header, fg_color="transparent")
        brand.grid(row=0, column=0, padx=14, pady=10, sticky="w")

        ctk.CTkLabel(
            brand,
            text="CompressPDF",
            font=ctk.CTkFont(size=27, weight="bold"),
            text_color="#f4f8ff",
        ).grid(row=0, column=0, sticky="w")

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.grid(row=1, column=0, padx=18, pady=(14, 12), sticky="nsew")
        content.grid_columnconfigure(0, weight=3)
        content.grid_columnconfigure(1, weight=2)
        content.grid_rowconfigure(0, weight=1)
        content.grid_rowconfigure(1, weight=0)

        left = ctk.CTkFrame(content, corner_radius=14, fg_color="#0c1f44", border_width=1, border_color="#1c335f")
        left.grid(row=0, column=0, padx=(0, 10), pady=0, sticky="nsew")
        left.grid_rowconfigure(0, weight=1)
        left.grid_columnconfigure(0, weight=1)

        right = ctk.CTkFrame(content, corner_radius=14, fg_color="#0c1f44", border_width=1, border_color="#1c335f")
        right.grid(row=0, column=1, padx=(10, 0), pady=0, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(8, weight=1)

        self.drop_area = ctk.CTkFrame(
            left,
            corner_radius=14,
            fg_color="#091a3a",
            border_width=0,
        )
        self.drop_area.grid(row=0, column=0, padx=14, pady=(14, 10), sticky="nsew")
        self.drop_area.grid_columnconfigure(0, weight=1)
        self.drop_area.grid_rowconfigure(0, weight=1)

        self.drop_dash_canvas = tk.Canvas(
            self.drop_area,
            bg="#091a3a",
            highlightthickness=0,
            bd=0,
            relief="flat",
        )
        self.drop_dash_canvas.place(relx=0.5, rely=0.5, relwidth=0.95, relheight=0.90, anchor="center")
        self.drop_dash_canvas.bind("<Configure>", self._redraw_drop_dash_border)
        self.drop_area.bind("<Enter>", self._on_drop_hover_enter)
        self.drop_area.bind("<Leave>", self._on_drop_hover_leave)

        self.empty_state = ctk.CTkFrame(self.drop_area, fg_color="transparent")
        self.empty_state.grid(row=0, column=0, sticky="nsew")
        self.empty_state.grid_columnconfigure(0, weight=1)

        self.ready_state = ctk.CTkFrame(self.drop_area, fg_color="transparent")
        self.ready_state.grid(row=0, column=0, sticky="nsew")
        self.ready_state.grid_columnconfigure(0, weight=1)
        self.ready_state.grid_rowconfigure(3, weight=1)
        self.ready_state.grid_remove()

        self.empty_state.lift()

        self.upload_icon_card = ctk.CTkFrame(self.empty_state, width=84, height=84, corner_radius=20, fg_color="#2a4f2f")
        self.upload_icon_card.grid(row=0, column=0, pady=(88, 14))
        self.upload_icon_card.grid_propagate(False)
        self.upload_icon_label = ctk.CTkLabel(
            self.upload_icon_card,
            text="☁",
            font=ctk.CTkFont(size=42, weight="bold"),
            text_color="#98ef35",
        )
        self.upload_icon_label.place(relx=0.5, rely=0.48, anchor="center")

        self.drop_title = ctk.CTkLabel(
            self.empty_state,
            text="Upload PDF",
            font=ctk.CTkFont(size=30, weight="bold"),
            text_color="#eff5ff",
        )
        self.drop_title.grid(row=1, column=0, pady=(0, 10))

        self.drop_desc = ctk.CTkLabel(
            self.empty_state,
            text="Drag and drop your files here, or",
            text_color="#a9b9d8",
            font=ctk.CTkFont(size=13),
            justify="center",
        )
        self.drop_desc.grid(row=2, column=0, pady=(0, 8))

        self.browse_link = self._create_styled_button(
            self.empty_state,
            text="Upload via browser",
            command=self.select_file,
            variant="primary",
            width=190,
            height=34,
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.browse_link.grid(row=3, column=0, pady=(0, 12))

        self.file_count_label = ctk.CTkLabel(
            self.empty_state,
            text="SUPPORTS MULTIPLE FILES • MAX 500MB+",
            font=ctk.CTkFont(size=11),
            text_color="#7f94be",
        )
        self.file_count_label.grid(row=4, column=0, pady=(0, 10))

        self.ready_icon_card = ctk.CTkFrame(self.ready_state, width=76, height=76, corner_radius=24, fg_color="#244c36")
        self.ready_icon_card.grid(row=0, column=0, pady=(24, 10))
        self.ready_icon_card.grid_propagate(False)
        ctk.CTkLabel(
            self.ready_icon_card,
            text="✔",
            font=ctk.CTkFont(size=30, weight="bold"),
            text_color="#97eb30",
        ).place(relx=0.48, rely=0.48, anchor="center")

        self.ready_badge = ctk.CTkFrame(self.ready_state, width=22, height=28, corner_radius=8, fg_color="#97eb30")
        self.ready_badge.place(relx=0.55, rely=0.20)
        self.ready_badge.grid_propagate(False)
        ctk.CTkLabel(
            self.ready_badge,
            text="✓",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#10213e",
        ).place(relx=0.5, rely=0.5, anchor="center")

        self.ready_title = ctk.CTkLabel(
            self.ready_state,
            text="File Ready to Process",
            font=ctk.CTkFont(size=28, weight="bold"),
            text_color="#eaf1ff",
        )
        self.ready_title.grid(row=1, column=0, pady=(0, 6))

        self.ready_desc = ctk.CTkLabel(
            self.ready_state,
            text="Your document has been successfully uploaded\nand is ready for compression.",
            font=ctk.CTkFont(size=14),
            justify="center",
            text_color="#9aadd1",
        )
        self.ready_desc.grid(row=2, column=0, pady=(0, 10))

        self.preview_wrap = ctk.CTkFrame(
            self.ready_state,
            fg_color="#0a1a39",
            border_width=1,
            border_color="#233f6d",
            corner_radius=18,
        )
        self.preview_wrap.grid(row=3, column=0, padx=32, pady=(0, 16), sticky="nsew")
        self.preview_wrap.grid_columnconfigure(0, weight=1)
        self.preview_wrap.grid_rowconfigure(0, weight=1)
        # force a minimum height for the preview row so the scrollable area can expand
        self.preview_wrap.grid_rowconfigure(0, minsize=220)

        self.preview_list = ctk.CTkScrollableFrame(
            self.preview_wrap,
            fg_color="transparent",
            corner_radius=14,
            height=220,
        )
        self.preview_list.grid(row=0, column=0, padx=8, pady=8, sticky="nsew")
        self.preview_list.grid_columnconfigure(0, weight=1)
        self.after(0, self._sync_preview_content_width)

        self.ready_upload_btn = self._create_styled_button(
            self.ready_state,
            text="Upload via browser",
            command=self.select_file,
            variant="primary",
            width=190,
            height=34,
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.ready_upload_btn.grid(row=4, column=0, pady=(0, 14))

        self._bind_preview_scroll_events()

        self.drop_area.drop_target_register(DND_FILES)
        self.drop_area.dnd_bind("<<DropEnter>>", self._on_drop_enter)
        self.drop_area.dnd_bind("<<DropLeave>>", self._on_drop_leave)
        self.drop_area.dnd_bind("<<Drop>>", self.handle_drop)

        output_frame = ctk.CTkFrame(left, corner_radius=12, fg_color="#102754", border_width=1, border_color="#254274")
        output_frame.grid(row=1, column=0, padx=14, pady=(0, 14), sticky="ew")
        output_frame.grid_columnconfigure(0, weight=0)
        output_frame.grid_columnconfigure(1, weight=1)
        output_frame.grid_columnconfigure(2, weight=0)

        icon_card = ctk.CTkFrame(
            output_frame,
            width=30,
            height=30,
            corner_radius=8,
            fg_color="#0b1f42",
        )
        icon_card.grid(row=0, column=0, padx=(12, 8), pady=(12, 0), sticky="w")
        icon_card.grid_propagate(False)
        ctk.CTkLabel(
            icon_card,
            text="📁",
            font=ctk.CTkFont(size=16),
            text_color="#9fb4e1",
        ).place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(
            output_frame,
            text="OUTPUT FOLDER",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#8ea4cf",
        ).grid(row=0, column=1, padx=(0, 12), pady=(10, 0), sticky="w")

        self.output_path_label = ctk.CTkLabel(
            output_frame,
            text=str(self.output_folder),
            anchor="w",
            font=ctk.CTkFont(size=13),
            text_color="#e9efff",
        )
        self.output_path_label.grid(row=1, column=1, padx=(0, 12), pady=(0, 10), sticky="ew")

        change_btn = self._create_styled_button(
            output_frame,
            text="Change",
            command=self._change_output_folder,
            variant="outline",
            width=84,
            height=30,
        )
        change_btn.configure(border_width=1, border_color="#88e53a")
        change_btn.grid(row=1, column=2, padx=(0, 12), pady=(0, 10), sticky="e")

        ctk.CTkLabel(
            right,
            text="COMPRESSION LEVEL",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#8ea4cf",
        ).grid(row=0, column=0, padx=14, pady=(16, 8), sticky="w")

        self.level_var = ctk.StringVar(value="Low")
        self.level_cards = {}

        level_descriptions = {
            "Low": "Ukuran file paling kecil, kualitas gambar berkurang cukup besar.",
            "Medium": "Keseimbangan terbaik antara ukuran file dan kualitas yang tetap jelas.",
            "High": "Kualitas tinggi untuk dokumen profesional dengan kompresi minimal.",
        }

        for row_index, level in enumerate(["Low", "Medium", "High"], start=1):
            card = ctk.CTkFrame(
                right,
                corner_radius=12,
                fg_color="#162c55",
                border_width=1,
                border_color="#304e82",
                height=92,
            )
            card.grid(row=row_index, column=0, padx=14, pady=7, sticky="ew")
            card.grid_columnconfigure(0, weight=1)

            title = ctk.CTkLabel(
                card,
                text=level,
                font=ctk.CTkFont(size=31 if level == "Low" else 29, weight="bold"),
                text_color="#f0f6ff",
            )
            title.grid(row=0, column=0, padx=16, pady=(10, 2), sticky="w")

            desc = ctk.CTkLabel(
                card,
                text=level_descriptions[level],
                font=ctk.CTkFont(size=12),
                text_color="#a5b8dc",
                justify="left",
                anchor="w",
            )
            desc.grid(row=1, column=0, padx=16, pady=(0, 10), sticky="w")

            radio = ctk.CTkRadioButton(
                card,
                text="",
                variable=self.level_var,
                value=level,
                width=24,
                fg_color="#97eb30",
                hover_color="#243c6a",
                border_color="#4a6699",
                border_width_unchecked=2,
                border_width_checked=5,
                corner_radius=999,
                command=lambda l=level: self._select_level_card(l),
            )
            radio.grid(row=0, column=1, rowspan=2, padx=(0, 18), pady=0, sticky="e")

            card.bind("<Button-1>", lambda _event, l=level: self._select_level_card(l))
            title.bind("<Button-1>", lambda _event, l=level: self._select_level_card(l))
            desc.bind("<Button-1>", lambda _event, l=level: self._select_level_card(l))

            self.level_cards[level] = {"frame": card, "title": title, "desc": desc}

        ctk.CTkFrame(right, height=1, fg_color="#284775").grid(
            row=4,
            column=0,
            padx=14,
            pady=(12, 10),
            sticky="ew",
        )

        action_row = ctk.CTkFrame(right, fg_color="transparent")
        action_row.grid(row=5, column=0, padx=14, pady=(0, 8), sticky="ew")
        action_row.grid_columnconfigure((0, 1), weight=1)

        self.cancel_btn = self._create_styled_button(
            action_row,
            text="Cancel",
            command=self._clear_selection,
            variant="secondary",
            height=44,
        )
        self.cancel_btn.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        self.compress_btn = self._create_styled_button(
            action_row,
            text="Compress Now",
            command=self.compress_pdf,
            variant="primary",
            height=44,
            font=ctk.CTkFont(size=16, weight="bold"),
        )
        self.compress_btn.grid(row=0, column=1, padx=(8, 0), sticky="ew")
        self._set_compress_button_busy(False)

        self.progress = ctk.CTkProgressBar(right, progress_color="#8de739", fg_color="#2a3c63")
        self.progress.grid(row=6, column=0, padx=14, pady=(2, 2), sticky="ew")
        self.progress.set(0)

        self.progress_text = ctk.CTkLabel(
            right,
            text="Idle",
            font=ctk.CTkFont(size=12),
            text_color="#9db1d8",
        )
        self.progress_text.grid(row=7, column=0, padx=14, pady=(0, 8), sticky="w")

        self.result_box = ctk.CTkTextbox(
            right,
            height=110,
            wrap="word",
            fg_color="#12284f",
            border_width=1,
            border_color="#2b4a7d",
            text_color="#e8f0ff",
        )
        self.result_box.grid(row=8, column=0, padx=14, pady=(0, 14), sticky="nsew")
        self.result_box.insert("1.0", "Hasil kompres akan ditampilkan di sini...\n")
        self.result_box.configure(state="disabled")

        self.progress.grid_remove()
        self.progress_text.grid_remove()
        self.result_box.grid_remove()

        footer = ctk.CTkFrame(content, corner_radius=14, fg_color="#0c1f44", border_width=1, border_color="#1c335f")
        footer.grid(row=1, column=0, columnspan=2, padx=0, pady=(14, 0), sticky="ew")
        footer.grid_columnconfigure((0, 1, 2), weight=1)
        footer.grid_columnconfigure(3, weight=2)

        storage_card = ctk.CTkFrame(
            footer,
            corner_radius=10,
            fg_color="#081938",
            border_width=1,
            border_color="#223a67",
        )
        storage_card.grid(row=0, column=0, padx=18, pady=10, sticky="ew")
        storage_card.grid_columnconfigure(0, weight=1)

        self.storage_saved_label = ctk.CTkLabel(
            storage_card,
            text="STORAGE SAVED\n0 MB",
            justify="left",
            anchor="w",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#f0f6ff",
        )
        self.storage_saved_label.grid(row=0, column=0, padx=12, pady=8, sticky="w")

        files_card = ctk.CTkFrame(
            footer,
            corner_radius=10,
            fg_color="#081938",
            border_width=1,
            border_color="#223a67",
        )
        files_card.grid(row=0, column=1, padx=18, pady=10, sticky="ew")
        files_card.grid_columnconfigure(0, weight=1)

        self.files_processed_label = ctk.CTkLabel(
            files_card,
            text="FILES PROCESSED\n0",
            justify="left",
            anchor="w",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#f0f6ff",
        )
        self.files_processed_label.grid(row=0, column=0, padx=12, pady=8, sticky="w")

        speed_card = ctk.CTkFrame(
            footer,
            corner_radius=10,
            fg_color="#081938",
            border_width=1,
            border_color="#223a67",
        )
        speed_card.grid(row=0, column=2, padx=18, pady=10, sticky="ew")
        speed_card.grid_columnconfigure(0, weight=1)

        self.avg_speed_label = ctk.CTkLabel(
            speed_card,
            text="AVG SPEED\n0.0s/file",
            justify="left",
            anchor="w",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#f0f6ff",
        )
        self.avg_speed_label.grid(row=0, column=0, padx=12, pady=8, sticky="w")

        self.runtime_label = ctk.CTkLabel(
            footer,
            text=f"Running on Python {sys.version_info.major}.{sys.version_info.minor}  ●",
            font=ctk.CTkFont(size=12),
            text_color="#a3b7df",
        )
        self.runtime_label.grid(row=0, column=3, padx=18, pady=12, sticky="e")

        self._select_level_card("Low")

    def _clear_selection(self) -> None:
        self.selected_files = []
        self._refresh_file_preview()
        self.progress.set(0)
        self.progress_text.configure(text="Idle")
        self.progress.grid_remove()
        self.progress_text.grid_remove()
        self.result_box.grid_remove()

    def _select_level_card(self, level: str) -> None:
        self.level_var.set(level)
        self.set_compression_level(level)

        for name, widgets in self.level_cards.items():
            if name == level:
                widgets["frame"].configure(fg_color="#1a355f", border_color="#8de739", border_width=2)
            else:
                widgets["frame"].configure(fg_color="#162c55", border_color="#304e82", border_width=1)

        self.update_idletasks()

    def _change_output_folder(self) -> None:
        path = ""
        use_tk_fallback = platform.system() != "Darwin"
        if platform.system() == "Darwin":  # macOS
            try:
                script = '''
tell application "System Events"
    activate
    set folderPath to choose folder with prompt "Pilih folder output"
    return POSIX path of folderPath
end tell
'''
                result = subprocess.run(
                    ["osascript", "-e", script],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0 and result.stdout.strip():
                    path = result.stdout.strip()
                elif result.returncode != 0:
                    stderr = (result.stderr or "").lower()
                    canceled = "user canceled" in stderr or "(-128)" in stderr
                    if not canceled:
                        use_tk_fallback = True
            except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
                use_tk_fallback = True

        if use_tk_fallback and not path:  # Fallback only when native dialog failed
            path = filedialog.askdirectory(title="Pilih folder output")

        if path:
            self.output_folder = Path(path)
            self.output_folder.mkdir(parents=True, exist_ok=True)
            self.output_path_label.configure(text=str(self.output_folder))

    def _append_result(self, text: str) -> None:
        if not self.result_box.winfo_ismapped():
            self.result_box.grid()
        self.result_box.configure(state="normal")
        self.result_box.insert("end", text + "\n")
        self.result_box.see("end")
        self.result_box.configure(state="disabled")

    def _set_files(self, files: list[str]) -> None:
        started = time.perf_counter()
        valid_files = [path for path in files if path.lower().endswith(".pdf") and Path(path).is_file()]
        invalid_count = len(files) - len(valid_files)
        if invalid_count > 0:
            messagebox.showwarning(
                "File tidak valid",
                f"{invalid_count} file diabaikan karena bukan PDF atau tidak ditemukan.",
            )

        existing = {str(Path(path).resolve()) for path in self.selected_files}
        duplicate_files: list[str] = []
        for file_path in valid_files:
            resolved = str(Path(file_path).resolve())
            if resolved not in existing:
                self.selected_files.append(file_path)
                existing.add(resolved)
            else:
                duplicate_files.append(Path(file_path).name)

        if duplicate_files:
            shown_names = ", ".join(sorted(set(duplicate_files))[:3])
            more_count = len(set(duplicate_files)) - 3
            suffix = f" dan {more_count} file lainnya" if more_count > 0 else ""
            messagebox.showinfo(
                "File sudah ada",
                f"File sudah ada di tabel: {shown_names}{suffix}.",
            )

        self._refresh_file_preview()
        elapsed_ms = (time.perf_counter() - started) * 1000
        self._log_perf(
            f"_set_files processed={len(files)} valid={len(valid_files)} duplicates={len(duplicate_files)} in {elapsed_ms:.1f} ms"
        )

    def _refresh_file_preview(self) -> None:
        started = time.perf_counter()
        for child in self.preview_list.winfo_children():
            child.destroy()

        count = len(self.selected_files)
        if count == 0:
            self.file_count_label.configure(text="SUPPORTS MULTIPLE FILES • MAX 500MB+")
            self.empty_state.grid()
            self.ready_state.grid_remove()
            self.empty_state.lift()
            return

        self.empty_state.grid_remove()
        self.ready_state.grid()
        self.ready_state.lift()

        for index, file_path in enumerate(self.selected_files):
            row = ctk.CTkFrame(
                self.preview_list,
                fg_color="#071736",
                border_width=1,
                border_color="#1e3a68",
                corner_radius=18,
                height=58,
            )
            row.grid(row=index, column=0, padx=3, pady=4, sticky="ew")
            row.grid_columnconfigure(1, weight=1)

            icon_bg = ctk.CTkFrame(
                row,
                width=40,
                height=40,
                corner_radius=12,
                fg_color="#2a1833",
            )
            icon_bg.grid(row=0, column=0, padx=(12, 10), pady=10, sticky="w")
            icon_bg.grid_propagate(False)
            ctk.CTkLabel(
                icon_bg,
                text="PDF",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#ff5967",
            ).place(relx=0.5, rely=0.5, anchor="center")

            name_and_meta = ctk.CTkFrame(row, fg_color="transparent")
            name_and_meta.grid(row=0, column=1, padx=(0, 8), pady=8, sticky="ew")
            name_and_meta.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(
                name_and_meta,
                text=Path(file_path).name,
                anchor="w",
                text_color="#e7f0ff",
                font=ctk.CTkFont(size=11, weight="bold"),
            ).grid(row=0, column=0, pady=(0, 1), sticky="w")

            file_size = self._human_size(Path(file_path).stat().st_size)
            ctk.CTkLabel(
                name_and_meta,
                text=f"{file_size}  •  UPLOADED",
                anchor="w",
                text_color="#8fa5cd",
                font=ctk.CTkFont(size=9),
            ).grid(row=1, column=0, sticky="w")

            remove_btn = ctk.CTkButton(
                row,
                text="✕",
                command=lambda idx=index: self._remove_selected_file_by_index(idx),
                fg_color="transparent",
                hover_color="#20385f",
                text_color="#96a9cd",
                width=26,
                height=26,
                font=ctk.CTkFont(size=16, weight="bold"),
                corner_radius=10,
            )
            remove_btn.configure(cursor="hand2")
            remove_btn.grid(row=0, column=2, padx=(0, 12), pady=6, sticky="e")

        self._sync_preview_content_width()

        # update scrollbar visibility after refreshing preview items
        try:
            self._update_preview_scrollbar_visibility()
        except Exception:
            pass

        elapsed_ms = (time.perf_counter() - started) * 1000
        if elapsed_ms >= 5:
            self._log_perf(f"_refresh_file_preview took {elapsed_ms:.1f} ms for {count} files")

    def _bind_preview_scroll_events(self) -> None:
        canvas = getattr(self.preview_list, "_parent_canvas", None)
        if canvas is None:
            return

        def on_mousewheel(event):
            if not self.preview_scroll_hover:
                return

            step = 0
            if event.delta != 0:
                step = -1 if event.delta > 0 else 1
            elif getattr(event, "num", None) == 4:
                step = -1
            elif getattr(event, "num", None) == 5:
                step = 1

            if step == 0:
                return "break"

            first, last = canvas.yview()
            if step < 0 and first <= 0.0:
                return "break"
            if step > 0 and last >= 1.0:
                return "break"

            canvas.yview_scroll(step, "units")
            return "break"

        def bind_wheel(_event):
            self.preview_scroll_hover = True
            canvas.bind("<MouseWheel>", on_mousewheel)
            canvas.bind("<Button-4>", on_mousewheel)
            canvas.bind("<Button-5>", on_mousewheel)

        def unbind_wheel(_event):
            self.preview_scroll_hover = False
            canvas.unbind("<MouseWheel>")
            canvas.unbind("<Button-4>")
            canvas.unbind("<Button-5>")

        self.preview_list.bind("<Enter>", bind_wheel)
        self.preview_list.bind("<Leave>", unbind_wheel)

        # keep content width and scrollbar visibility updated on resize (throttled)
        try:
            canvas.bind("<Configure>", self._schedule_preview_layout_update)
        except Exception:
            pass

    def _schedule_preview_layout_update(self, _event=None) -> None:
        if self.preview_layout_job is not None:
            try:
                self.after_cancel(self.preview_layout_job)
            except Exception:
                pass
        self.preview_layout_job = self.after(16, self._apply_preview_layout_update)

    def _apply_preview_layout_update(self) -> None:
        started = time.perf_counter()
        self.preview_layout_job = None
        self._sync_preview_content_width()
        self._update_preview_scrollbar_visibility()
        elapsed_ms = (time.perf_counter() - started) * 1000
        if elapsed_ms >= 6:
            self._log_perf(f"Preview layout update took {elapsed_ms:.1f} ms")

    def _sync_preview_content_width(self, _event=None) -> None:
        """Keep scrollable content width aligned with the visible canvas width."""
        if not hasattr(self, "preview_list"):
            return

        try:
            canvas = getattr(self.preview_list, "_parent_canvas", None)
            window_id = getattr(self.preview_list, "_create_window_id", None)
            if canvas is None or window_id is None:
                return

            canvas_width = canvas.winfo_width()
            if canvas_width <= 1:
                return

            target_width = max(220, canvas_width - 2)
            current_width = canvas.itemcget(window_id, "width")
            try:
                current_width_int = int(float(current_width)) if current_width else 0
            except Exception:
                current_width_int = 0

            if current_width_int != target_width:
                canvas.itemconfigure(window_id, width=target_width)
        except Exception:
            return

    def _update_preview_scrollbar_visibility(self) -> None:
        """Always hide internal scrollbar visuals while keeping wheel scrolling active."""
        canvas = getattr(self.preview_list, "_parent_canvas", None)
        if canvas is None:
            return

        try:
            first, last = canvas.yview()
        except Exception:
            return

        scrollbar = self.preview_scrollbar_widget
        if scrollbar is None or not scrollbar.winfo_exists():
            scrollbar = getattr(self.preview_list, "_scrollbar", None)
            if scrollbar is None:
                # fallback: search one level deep only
                for widget in (self.preview_wrap, self.preview_list, canvas.master):
                    for child in widget.winfo_children():
                        try:
                            cls = child.winfo_class().lower()
                        except Exception:
                            cls = ""
                        if isinstance(child, tk.Scrollbar) or "scrollbar" in cls:
                            scrollbar = child
                            break
                    if scrollbar is not None:
                        break
            self.preview_scrollbar_widget = scrollbar

        if scrollbar is None:
            return

        try:
            mgr = scrollbar.winfo_manager()
            if mgr == "grid":
                scrollbar.grid_remove()
            elif mgr == "pack":
                scrollbar.pack_forget()
            else:
                scrollbar.place_forget()
        except Exception:
            return

    def _remove_selected_file_by_index(self, index: int) -> None:
        if 0 <= index < len(self.selected_files):
            del self.selected_files[index]
            self._refresh_file_preview()
            self.update_idletasks()

    def select_file(self) -> None:
        """Select one or multiple PDF files via file dialog."""
        # Show busy state before blocking dialog
        self.config(cursor="wait")
        buttons_to_disable = [self.browse_link, self.ready_upload_btn, self.cancel_btn, self.compress_btn]
        for btn in buttons_to_disable:
            try:
                btn.configure(state="disabled")
            except Exception:
                pass
        self.update_idletasks()  # Process UI updates before blocking

        files = []
        use_tk_fallback = platform.system() != "Darwin"
        if platform.system() == "Darwin":  # macOS
            try:
                script = '''
tell application "System Events"
    activate
    set fileList to choose file with prompt "Pilih file PDF" of type {"PDF"} multiple selections allowed without invisibles
    set filePaths to ""
    repeat with aFile in fileList
        set filePaths to filePaths & (POSIX path of aFile) & "\n"
    end repeat
    return filePaths
end tell
'''
                result = subprocess.run(
                    ["osascript", "-e", script],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0 and result.stdout.strip():
                    files = [p.strip() for p in result.stdout.strip().split("\n") if p.strip()]
                elif result.returncode != 0:
                    stderr = (result.stderr or "").lower()
                    canceled = "user canceled" in stderr or "(-128)" in stderr
                    if not canceled:
                        use_tk_fallback = True
            except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
                use_tk_fallback = True

        if use_tk_fallback and not files:  # Fallback only when native dialog failed
            files = list(filedialog.askopenfilenames(
                title="Pilih file PDF",
                filetypes=[("PDF Files", "*.pdf")],
            ))

        # Restore UI state
        self.config(cursor="")
        for btn in buttons_to_disable:
            try:
                btn.configure(state="normal")
            except Exception:
                pass

        if files:
            self._set_files(files)

    def handle_drop(self, event) -> None:
        """Handle drag-and-drop file input."""
        self._stop_drop_animation()
        dropped = self.tk.splitlist(event.data)
        normalized = []
        for item in dropped:
            clean_path = item.strip("{}")
            normalized.append(clean_path)
        self._set_files(normalized)

    def _on_drop_enter(self, event):
        self._start_drop_animation()
        return event.action

    def _on_drop_leave(self, event):
        self._stop_drop_animation()
        return event.action

    def _start_drop_animation(self) -> None:
        if self.is_drag_active:
            return
        self.is_drag_active = True
        self.drag_animation_step = 0
        self.drop_desc.configure(text="Lepaskan file PDF di sini")
        self._animate_drop_pulse()

    def _on_drop_hover_enter(self, _event=None) -> None:
        if self.is_drag_active:
            return
        try:
            self.drop_area.configure(fg_color="#0c2248")
            self.drop_dash_canvas.itemconfig("dash-border", outline="#3a5f95")
        except Exception:
            pass

    def _on_drop_hover_leave(self, _event=None) -> None:
        if self.is_drag_active:
            return
        try:
            self.drop_area.configure(fg_color="#091a3a")
            self.drop_dash_canvas.itemconfig("dash-border", outline="#2b4776")
        except Exception:
            pass

    def _redraw_drop_dash_border(self, _event=None) -> None:
        canvas = getattr(self, "drop_dash_canvas", None)
        if canvas is None:
            return

        canvas.delete("dash-border")
        width = max(4, canvas.winfo_width())
        height = max(4, canvas.winfo_height())
        pad = 4

        canvas.create_rectangle(
            pad,
            pad,
            width - pad,
            height - pad,
            outline="#2b4776",
            width=1,
            dash=(5, 7),
            tags="dash-border",
        )

    def _animate_drop_pulse(self) -> None:
        if not self.is_drag_active:
            return

        border_colors = ["#4d6faa", "#89f044", "#5f89d6", "#3f6ab8"]
        icon_card_colors = ["#2f5b34", "#3f6d3d", "#315d36", "#2a4f2f"]
        icon_text_colors = ["#afff58", "#d4ff91", "#bffd61", "#98ef35"]

        idx = self.drag_animation_step % len(border_colors)
        self.drop_dash_canvas.itemconfig("dash-border", outline=border_colors[idx])
        self.upload_icon_card.configure(fg_color=icon_card_colors[idx])
        self.upload_icon_label.configure(text_color=icon_text_colors[idx])

        self.drag_animation_step += 1
        self.drag_animation_job = self.after(160, self._animate_drop_pulse)

    def _stop_drop_animation(self) -> None:
        self.is_drag_active = False
        if self.drag_animation_job is not None:
            self.after_cancel(self.drag_animation_job)
            self.drag_animation_job = None

        self.drop_dash_canvas.itemconfig("dash-border", outline="#2b4776")
        self.upload_icon_card.configure(fg_color="#2a4f2f")
        self.upload_icon_label.configure(text_color="#98ef35")
        self.drop_desc.configure(text="Drag and drop your files here, or")

    def set_compression_level(self, level: str) -> None:
        """Set compression level from UI selection."""
        self.compression_level = level

    @staticmethod
    def calculate_percentage(original_size: int, compressed_size: int) -> float:
        """Calculate percentage reduction between original and compressed file."""
        if original_size <= 0:
            return 0.0
        return ((original_size - compressed_size) / original_size) * 100

    def _find_ghostscript(self) -> str | None:
        """Find Ghostscript executable path for current OS."""
        bundled_candidates = []
        base_dir = self._runtime_base_dir()
        if os.name == "nt":
            bundled_candidates.extend(
                [
                    base_dir / "ghostscript" / "gswin64c.exe",
                    base_dir / "ghostscript" / "gswin32c.exe",
                    base_dir / "gswin64c.exe",
                    base_dir / "gswin32c.exe",
                ]
            )
        else:
            bundled_candidates.extend(
                [
                    base_dir / "ghostscript" / "gs",
                    base_dir / "ghostscript" / "bin" / "gs",
                    base_dir / "gs",
                ]
            )

        for candidate in bundled_candidates:
            if candidate.exists() and candidate.is_file():
                return str(candidate)

        candidates = []
        if os.name == "nt":
            candidates.extend(["gswin64c", "gswin32c", "gs"])
        else:
            candidates.extend(["gs", "/opt/homebrew/bin/gs", "/usr/local/bin/gs"])

        for cmd in candidates:
            resolved = shutil.which(cmd)
            if resolved:
                return resolved

        return None

    @staticmethod
    def _runtime_base_dir() -> Path:
        """Get runtime base directory for normal run and PyInstaller bundle."""
        if getattr(sys, "frozen", False):
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                return Path(meipass)
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parent

    def _build_output_path(self, source_file: str) -> Path:
        src = Path(source_file)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.output_folder / f"{src.stem}_compressed_{timestamp}.pdf"

    def compress_pdf(self) -> None:
        """Compress selected PDFs in a background thread."""
        if self.is_processing:
            return

        if not self.selected_files:
            messagebox.showerror("Tidak ada file", "Pilih atau drop minimal satu file PDF.")
            return

        if self.gs_path is None:
            self.gs_path = self._find_ghostscript()
        if not self.gs_path:
            messagebox.showerror(
                "Ghostscript tidak ditemukan",
                "Ghostscript belum terinstall atau belum masuk PATH.\n"
                "Install Ghostscript terlebih dahulu:\n"
                "- macOS: brew install ghostscript\n"
                "- Windows: install dari https://ghostscript.com/releases/",
            )
            return

        self.is_processing = True
        self._set_compress_button_busy(True)
        self.progress.grid()
        self.progress_text.grid()
        self.result_box.grid()
        self.progress.set(0)
        self.progress_text.configure(text="Memulai kompres...")

        worker = threading.Thread(
            target=self._compress_worker,
            args=(self.gs_path, self.selected_files.copy(), self.compression_level),
            daemon=True,
        )
        worker.start()

    def _compress_worker(self, gs_path: str, files: list[str], level: str) -> None:
        preset = COMPRESSION_MAP.get(level, "/ebook")
        total = len(files)

        for index, pdf_file in enumerate(files, start=1):
            source = Path(pdf_file)
            output = self._build_output_path(pdf_file)
            started_at = time.perf_counter()

            original_size = source.stat().st_size
            self.queue.put(("progress_text", f"Memproses {index}/{total}: {source.name}"))

            cmd = [
                gs_path,
                "-sDEVICE=pdfwrite",
                "-dCompatibilityLevel=1.4",
                "-dNOPAUSE",
                "-dQUIET",
                "-dBATCH",
                f"-dPDFSETTINGS={preset}",
                f"-sOutputFile={str(output)}",
                str(source),
            ]

            try:
                subprocess.run(cmd, check=True, capture_output=True, text=True)
                if not output.exists():
                    raise RuntimeError("Output file tidak terbentuk.")

                compressed_size = output.stat().st_size
                percentage = self.calculate_percentage(original_size, compressed_size)
                saved = max(0, original_size - compressed_size)

                self.total_saved_bytes += saved
                self.total_processed += 1
                self.total_elapsed_seconds += max(0.001, time.perf_counter() - started_at)

                result_line = (
                    f"✅ {source.name}\n"
                    f"   Sebelum: {self._human_size(original_size)}\n"
                    f"   Sesudah: {self._human_size(compressed_size)}\n"
                    f"   Pengurangan: -{percentage:.2f}%\n"
                    f"   Hasil: {output}\n"
                )
                self.queue.put(("result", result_line))
                self.queue.put(("stats", None))

            except subprocess.CalledProcessError as err:
                stderr = (err.stderr or "").strip()
                msg = stderr if stderr else "Gagal menjalankan Ghostscript."
                self.queue.put(("error", f"❌ {source.name}: {msg}"))
            except Exception as err:
                self.queue.put(("error", f"❌ {source.name}: {err}"))

            self.queue.put(("progress", index / total))

        self.queue.put(("done", None))

    def _process_queue(self) -> None:
        started = time.perf_counter()
        max_events_per_tick = 20
        processed = 0

        while not self.queue.empty() and processed < max_events_per_tick:
            event, payload = self.queue.get_nowait()
            processed += 1

            if event == "result":
                self._append_result(payload)
            elif event == "error":
                self._append_result(payload)
            elif event == "progress":
                self.progress.set(payload)
            elif event == "progress_text":
                self.progress_text.configure(text=payload)
            elif event == "stats":
                self.storage_saved_label.configure(
                    text=f"STORAGE SAVED\n{self._human_size(self.total_saved_bytes)}"
                )
                self.files_processed_label.configure(text=f"FILES PROCESSED\n{self.total_processed}")
                avg_time = self.total_elapsed_seconds / self.total_processed if self.total_processed else 0.0
                self.avg_speed_label.configure(text=f"AVG SPEED\n{avg_time:.1f}s/file")
            elif event == "done":
                self.is_processing = False
                self._set_compress_button_busy(False)
                self.progress_text.configure(text="Selesai")

        next_delay = 60 if self.is_processing else 180
        elapsed_ms = (time.perf_counter() - started) * 1000
        if processed > 0 and elapsed_ms >= 6:
            self._log_perf(f"Queue tick processed={processed} took {elapsed_ms:.1f} ms")
        self.queue_poll_job = self.after(next_delay, self._process_queue)

    @staticmethod
    def _human_size(num_bytes: int) -> str:
        size = float(num_bytes)
        units = ["B", "KB", "MB", "GB", "TB"]
        for unit in units:
            if size < 1024 or unit == units[-1]:
                return f"{size:.2f} {unit}"
            size /= 1024
        return f"{num_bytes} B"


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
