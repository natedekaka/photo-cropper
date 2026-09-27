#!/usr/bin/env python3
"""
Batch Photo Cropper GTK - Aplikasi crop foto/gambar secara batch untuk pas foto.
Mendukung preset ukuran Indonesia dan ukuran custom.
Disusun dengan PyGObject (GTK3) + Pillow + Cairo.
"""

import cairo
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib

from PIL import Image

# ── Preset ukuran pas foto (lebar x tinggi dalam mm) ──────────────────────
PRESETS = [
    ("3x4 cm (Pas Foto)", 30, 40),
    ("2x3 cm", 20, 30),
    ("4x6 cm", 40, 60),
    ("2x2 cm", 20, 20),
    ("3x3 cm", 30, 30),
    ("5x7 cm", 50, 70),
    ("6x8 cm", 60, 80),
    ("UK Passport (35x45mm)", 35, 45),
    ("US Passport (2x2 in)", 51, 51),
    ("Custom Size", None, None),
]

EXPORT_EXT = {
    "JPEG": (".jpg", "jpeg"),
    "PNG": (".png", "png"),
    "WEBP": (".webp", "webp"),
    "BMP": (".bmp", "bmp"),
}

COLOR_BG = "#1e1e1e"
COLOR_ACCENT = "#00d97e"
COLOR_BORDER = "#3a3a3a"
COLOR_TEXT = "#e6e6e6"
COLOR_MUTED = "#9a9a9a"
COLOR_OVERLAY = (0.0, 0.0, 0.0, 0.6)


class Theme:
    @staticmethod
    def apply():
        css = b"""
        * {
            font-family: 'Segoe UI', 'Inter', 'Noto Sans', sans-serif;
            font-size: 14px;
        }
        window, .bg { background-color: #1e1e1e; }
        .panel {
            background-color: #262626;
            border-radius: 8px;
            padding: 10px;
        }
        label { color: #e6e6e6; }
        label.muted { color: #9a9a9a; font-size: 12px; }
        label.title {
            color: #00d97e; font-size: 15px; font-weight: bold;
            background-color: transparent;
        }
        entry, combobox, spinbutton {
            background-color: #333333;
            color: #e6e6e6;
            border: 1px solid #4a4a4a;
            border-radius: 4px;
            padding: 5px;
        }
        button {
            background-image: none;
            background-color: #3a3a3a;
            color: #e6e6e6;
            border: 1px solid #4a4a4a;
            border-radius: 6px;
            padding: 6px 12px;
        }
        button:hover { background-color: #464646; }
        button:active { background-color: #2a2a2a; }
        button.accent {
            background-image: none;
            background-color: #00b863;
            color: #0d0d0d;
            font-weight: bold;
            border: none;
        }
        button.accent:hover { background-color: #00d97e; }
        scale trough { background-color: #3a3a3a; border-radius: 3px; }
        scale highlight { background-color: #00b863; border-radius: 3px; }
        combobox > button { background-color: #333333; }
        .thumb-selected {
            background-color: rgba(0, 217, 126, 0.25);
            border-radius: 4px;
        }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )


class CropCanvas(Gtk.DrawingArea):
    """Drawing area untuk preview dan interaksi crop box."""

    HANDLE = 14

    def __init__(self, app):
        super().__init__()
        self.app = app
        self._photo = None          # Pixbuf ditampilkan (sudah di-scale)
        self._display_key = None    # (width, height, index)
        self.off_x = 0
        self.off_y = 0
        self.disp_w = 0
        self.disp_h = 0
        self.scale = 1.0

        self.crop = None  # (x1,y1,x2,y2) display coords
        self.drag_mode = None  # 'move' | 'resize-lt' etc
        self.drag_anchor = None
        self.drag_orig_crop = None

        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
            | Gdk.EventMask.SCROLL_MASK
            | Gdk.EventMask.POINTER_MOTION_HINT_MASK
        )
        self.connect("draw", self.on_draw)
        self.connect("button-press-event", self.on_press)
        self.connect("motion-notify-event", self.on_motion)
        self.connect("button-release-event", self.on_release)
        self.connect("scroll-event", self.on_scroll)

    # ── Display setup ─────────────────────────────────────────────────────

    def refresh(self):
        """(Re)hitung layout gambar dan crop box."""
        img = self.app.current_image()
        if img is None:
            return
        alloc = self.get_allocation()
        cw, ch = alloc.width, alloc.height
        iw, ih = img.get_width(), img.get_height()
        key = (cw, ch, self.app.current_index)
        if self._display_key != key:
            s = min(cw / iw, ch / ih, 1.0)
            nw, nh = max(1, int(iw * s)), max(1, int(ih * s))
            scaled = img.scale_simple(nw, nh, GdkPixbuf.InterpType.BILINEAR)
            self._photo = scaled
            self.off_x = (cw - nw) // 2
            self.off_y = (ch - nh) // 2
            self.disp_w, self.disp_h = nw, nh
            self.scale = s
            self._display_key = key
            if self.img_changed():
                self.place_default_crop()

    def img_changed(self):
        return self._display_key is not None and self._display_key[2] == \
            self.app.current_index

    def place_default_crop(self):
        ocm = self.app.output_width_mm
        ohm = self.app.output_height_mm
        rw, rh = ocm, ohm
        cw, ch = self.disp_w, self.disp_h

        # ukuran crop dalam display coords bila pas foto @300dpi
        target_w = ocm * 300 / 25.4 * self.scale
        target_h = ohm * 300 / 25.4 * self.scale
        if rw > rh:
            if target_w > cw:
                target_w = cw
                target_h = target_w * rh / rw
        else:
            if target_h > ch:
                target_h = ch
                target_w = target_h * rw / rh

        x1 = self.off_x + (cw - target_w) / 2
        y1 = self.off_y + (ch - target_h) / 2
        x2 = x1 + target_w
        y2 = y1 + target_h
        self.crop = (x1, y1, x2, y2)

    # ── Drawing ───────────────────────────────────────────────────────────

    def on_draw(self, wa, ctx):
        ctx.set_source_rgb(0.12, 0.12, 0.12)
        ctx.paint()

        if self._photo is None:
            self._draw_placeholder(ctx)
            return

        # Draw gambar
        Gdk.cairo_set_source_pixbuf(ctx, self._photo, self.off_x, self.off_y)
        ctx.paint()

        if self.crop is None:
            return

        x1, y1, x2, y2 = self.crop
        x1, y1, x2, y2 = map(float, (x1, y1, x2, y2))

        # Gelapkan area di luar crop
        area_x, area_y = self.off_x, self.off_y
        area_w, area_h = self.disp_w, self.disp_h

        ctx.set_source_rgba(*COLOR_OVERLAY)
        # top
        ctx.rectangle(area_x, area_y, area_w, y1 - area_y)
        ctx.fill()
        # bottom
        ctx.rectangle(area_x, y2, area_w, area_y + area_h - y2)
        ctx.fill()
        # left
        ctx.rectangle(area_x, y1, x1 - area_x, y2 - y1)
        ctx.fill()
        # right
        ctx.rectangle(x2, y1, area_x + area_w - x2, y2 - y1)
        ctx.fill()

        # Border crop
        ctx.set_source_rgb(0.0, 0.85, 0.49)
        ctx.set_line_width(2.0)
        ctx.rectangle(x1, y1, x2 - x1, y2 - y1)
        ctx.stroke()

        # Rule of thirds
        ctx.set_source_rgba(0.0, 0.85, 0.49, 0.45)
        ctx.set_line_width(1.0)
        ctx.set_dash([4, 4], 0)
        for i in range(1, 3):
            lx = x1 + (x2 - x1) * i / 3
            ly = y1 + (y2 - y1) * i / 3
            ctx.move_to(lx, y1)
            ctx.line_to(lx, y2)
            ctx.stroke()
            ctx.move_to(x1, ly)
            ctx.line_to(x2, ly)
            ctx.stroke()
        ctx.set_dash([], 0)

        # Corner handles
        hs = self.HANDLE / 2
        for hx, hy in ((x1, y1), (x2, y1), (x1, y2), (x2, y2)):
            ctx.rectangle(hx - hs, hy - hs, hs * 2, hs * 2)
            ctx.set_source_rgb(0.0, 0.85, 0.49)
            ctx.fill()
            ctx.rectangle(hx - hs, hy - hs, hs * 2, hs * 2)
            ctx.set_source_rgba(0.0, 0.4, 0.2, 1.0)
            ctx.set_line_width(1.0)
            ctx.stroke()

        return False

    def _draw_placeholder(self, ctx):
        alloc = self.get_allocation()
        ctx.set_source_rgba(0.18, 0.18, 0.18, 1.0)
        ctx.set_font_size(18)
        ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL,
                             cairo.FONT_WEIGHT_NORMAL)
        ctx.set_source_rgba(0.6, 0.6, 0.6, 1.0)
        text = "Klik 'Pilih Foto' untuk memulai"
        ext = ctx.text_extents(text)
        ctx.move_to((alloc.width - ext.width) / 2, (alloc.height - ext.height) / 2)
        ctx.show_text(text)

    # ── Interaksi ─────────────────────────────────────────────────────────

    def on_press(self, wa, ev):
        if self.crop is None:
            return False
        x1, y1, x2, y2 = self.crop
        hs = self.HANDLE

        # Resize handles
        corners = {
            "tl": (x1, y1), "tr": (x2, y1),
            "bl": (x1, y2), "br": (x2, y2),
        }
        if ev.button == 1:
            for name, (cx, cy) in corners.items():
                if abs(ev.x - cx) <= hs and abs(ev.y - cy) <= hs:
                    self.drag_mode = f"resize-{name}"
                    self.drag_anchor = (ev.x, ev.y)
                    self.drag_orig_crop = self.crop
                    return True
            if x1 <= ev.x <= x2 and y1 <= ev.y <= y2:
                self.drag_mode = "move"
                self.drag_anchor = (ev.x, ev.y)
                self.drag_orig_crop = self.crop
                return True
        return False

    def on_motion(self, wa, ev):
        if self.drag_mode is None or self.drag_orig_crop is None:
            return False

        ax, ay = self.drag_anchor
        dx = ev.x - ax
        dy = ev.y - ay
        x1, y1, x2, y2 = self.drag_orig_crop
        ocm, ohm = self.app.output_width_mm, self.app.output_height_mm

        min_s = 20.0
        min_px_w = min(min_s, ocm)
        min_px_h = min(min_s, ohm)
        rw, rh = float(ocm), float(ohm)

        if self.drag_mode == "move":
            nw, nh = (x2 - x1), (y2 - y1)
            nx1, ny1 = x1 + dx, y1 + dy
            nx2, ny2 = nx1 + nw, ny1 + nh
            if nx1 < self.off_x:
                nx2 += self.off_x - nx1
                nx1 = self.off_x
            if ny1 < self.off_y:
                ny2 += self.off_y - ny1
                ny1 = self.off_y
            if nx2 > self.off_x + self.disp_w:
                nx1 -= nx2 - (self.off_x + self.disp_w)
                nx2 = self.off_x + self.disp_w
            if ny2 > self.off_y + self.disp_h:
                ny1 -= ny2 - (self.off_y + self.disp_h)
                ny2 = self.off_y + self.disp_h
            self.crop = (nx1, ny1, nx2, ny2)

        else:
            corner = self.drag_mode.split("-")[1]
            if corner in ("br", "tr"):
                new_w = max(min_px_w, x2 + dx - x1)
            else:
                new_w = max(min_px_w, x2 - (x1 + dx))
            new_h = max(min_px_h, new_w * rh / rw)

            if corner == "br":
                nx1, ny1 = x1, y1
                nx2, ny2 = x1 + new_w, y1 + new_h
            elif corner == "tl":
                nx1, ny1 = x2 - new_w, y2 - new_h
                nx2, ny2 = x2, y2
            elif corner == "tr":
                nx1, ny1 = x1, y2 - new_h
                nx2, ny2 = x1 + new_w, y2
            else:  # bl
                nx1, ny1 = x2 - new_w, y1
                nx2, ny2 = x2, y1 + new_h

            # clamp
            nx1 = max(self.off_x, nx1)
            ny1 = max(self.off_y, ny1)
            nx2 = min(self.off_x + self.disp_w, nx2)
            ny2 = min(self.off_y + self.disp_h, ny2)
            if (nx2 - nx1) < 1 or (ny2 - ny1) < 1:
                return True
            self.crop = (nx1, ny1, nx2, ny2)

        self.queue_draw()
        return True

    def on_release(self, wa, ev):
        self.drag_mode = None
        self.drag_anchor = None
        self.drag_orig_crop = None
        return False

    def on_scroll(self, wa, ev):
        step = -1 if ev.delta_y > 0 else 1
        self.app.nav_image(step)
        return True


class PhotoCropperApp:
    def __init__(self):
        self.images: list[GdkPixbuf.Pixbuf] = []
        self.paths: list[Path] = []
        self.current_index = 0

        self.output_width_mm = 30
        self.output_height_mm = 40
        self.dpi = 300
        self.format = "JPEG"
        self.quality = 95

        self.window = Gtk.Window(title="Batch Photo Cropper - Pas Foto")
        self.window.set_default_size(1180, 760)
        self.window.set_position(Gtk.WindowPosition.CENTER)
        self.window.connect("destroy", Gtk.main_quit)

        self._build_ui()
        self.window.show_all()

    # ── UI ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        hpaned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.window.add(hpaned)

        # ── Left: control panel ──
        left = Gtk.VBox(spacing=8)
        left.set_size_request(300, -1)
        left.set_margin_top(8)
        left.set_margin_bottom(8)
        hpaned.pack1(left, resize=False, shrink=False)

        # -- File
        left.pack_start(Gtk.Label(label="Batch Photo Cropper"),
                        False, False, 0)
        left.pack_start(self._label("Crop banyak foto sekaligus untuk pas foto",
                                    cls="muted"), False, False, 0)

        self._section = Gtk.VBox()

        # File section
        file_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        file_box.get_style_context().add_class("panel")
        pick = Gtk.Button(label="📂 Pilih Foto...")
        pick.connect("clicked", self._on_pick)
        file_box.pack_start(pick, False, False, 0)
        self.lbl_count = self._label("0 foto dipilih", cls="muted")
        file_box.pack_start(self.lbl_count, False, False, 0)

        add = Gtk.Button(label="➕ Tambah Foto lagi")
        add.connect("clicked", self._on_pick)
        file_box.pack_start(add, False, False, 0)

        # Size section
        size_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        size_box.get_style_context().add_class("panel")
        size_box.pack_start(self._label("📐 Ukuran Output", cls="title"),
                            False, False, 0)

        self.preset_combo = Gtk.ComboBoxText()
        for name, *_ in PRESETS:
            self.preset_combo.append_text(name)
        self.preset_combo.set_active(0)
        self.preset_combo.connect("changed", self._on_preset)
        size_box.pack_start(self.preset_combo, False, False, 0)

        wh = Gtk.Box(spacing=6)
        wh.pack_start(self._label("Lebar"), False, False, 0)
        self.entry_w = Gtk.Entry()
        self.entry_w.set_width_chars(5)
        self.entry_w.set_text(str(self.output_width_mm))
        wh.pack_start(self.entry_w, False, False, 0)
        wh.pack_start(self._label("mm"), False, False, 0)
        wh.pack_start(self._label("Tinggi"), False, False, 0)
        self.entry_h = Gtk.Entry()
        self.entry_h.set_width_chars(5)
        self.entry_h.set_text(str(self.output_height_mm))
        wh.pack_start(self.entry_h, False, False, 0)
        wh.pack_start(self._label("mm"), False, False, 0)
        size_box.pack_start(wh, False, False, 0)

        self.btn_apply = Gtk.Button(label="Terapkan Ukuran")
        self.btn_apply.connect("clicked", self._on_apply_size)
        size_box.pack_start(self.btn_apply, False, False, 0)

        self.lbl_ratio = self._label("", cls="muted")
        size_box.pack_start(self.lbl_ratio, False, False, 0)

        self.lbl_output_px = self._label("", cls="muted")
        size_box.pack_start(self.lbl_output_px, False, False, 0)

        # Output section
        out_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        out_box.get_style_context().add_class("panel")
        out_box.pack_start(self._label("💾 Output", cls="title"),
                           False, False, 0)

        fmt_row = Gtk.Box(spacing=6)
        fmt_row.pack_start(self._label("Format:"), False, False, 0)
        self.fmt_combo = Gtk.ComboBoxText()
        for name in EXPORT_EXT:
            self.fmt_combo.append_text(name)
        self.fmt_combo.set_active(0)
        self.fmt_combo.connect("changed", self._on_format)
        fmt_row.pack_start(self.fmt_combo, True, True, 0)
        out_box.pack_start(fmt_row, False, False, 0)

        dpi_row = Gtk.Box(spacing=6)
        dpi_row.pack_start(self._label("DPI:"), False, False, 0)
        self.dpi_combo = Gtk.ComboBoxText()
        for d in ("72", "96", "150", "300", "600"):
            self.dpi_combo.append_text(d)
        self.dpi_combo.set_active(3)
        self.dpi_combo.connect("changed", self._on_dpi)
        dpi_row.pack_start(self.dpi_combo, True, True, 0)
        out_box.pack_start(dpi_row, False, False, 0)

        out_box.pack_start(self._label("Quality (JPEG/WEBP):"), False, False, 0)
        adj = Gtk.Adjustment(
            value=95, lower=10, upper=100, step_increment=1,
            page_increment=10, page_size=0,
        )
        self.quality_scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL,
                                       adjustment=adj)
        self.quality_scale.set_hexpand(True)
        self.quality_scale.connect("value-changed", self._on_quality)
        out_box.pack_start(self.quality_scale, False, False, 0)
        self.lbl_quality = self._label("95%", cls="muted")
        out_box.pack_start(self.lbl_quality, False, False, 0)

        # Actions
        act_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        act_box.get_style_context().add_class("panel")
        act_box.pack_start(self._label("⚡ Aksi", cls="title"), False, False, 0)

        self.btn_preview = Gtk.Button(label="👁  Preview Semua")
        self.btn_preview.connect("clicked", self._on_preview)
        act_box.pack_start(self.btn_preview, False, False, 0)

        self.btn_export = Gtk.Button(label="💾  Export Semua...")
        self.btn_export.get_style_context().add_class("accent")
        self.btn_export.connect("clicked", self._on_export)
        act_box.pack_start(self.btn_export, False, False, 0)

        self.btn_remove = Gtk.Button(label="🗑  Hapus Foto Terpilih")
        self.btn_remove.connect("clicked", self._on_remove)
        act_box.pack_start(self.btn_remove, False, False, 0)

        for b in (file_box, size_box, out_box, act_box):
            left.pack_start(b, False, False, 0)

        # ── Right: canvas + thumbnails ──
        right = Gtk.VBox(spacing=4)
        right.set_margin_top(8)
        right.set_margin_bottom(8)
        right.set_margin_end(8)
        hpaned.pack2(right, resize=True, shrink=False)

        self.canvas = CropCanvas(self)
        self.canvas.set_hexpand(True)
        self.canvas.set_vexpand(True)
        right.pack_start(self.canvas, True, True, 0)

        self.thumb_box = Gtk.FlowBox()
        self.thumb_box.set_valign(Gtk.Align.CENTER)
        self.thumb_box.set_max_children_per_line(10)
        self.thumb_box.set_selection_mode(Gtk.SelectionMode.NONE)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER)
        scroller.set_min_content_height(110)
        scroller.add(self.thumb_box)
        right.pack_start(scroller, False, False, 0)

        # Status bar
        self.status_var = Gtk.Label(label="Siap — Pilih foto untuk mulai")
        self.status_var.get_style_context().add_class("muted")
        self.status_var.set_halign(Gtk.Align.START)
        right.pack_start(self.status_var, False, False, 0)

        # Keyboard
        self.window.connect("key-press-event", self._on_key)

        self._refresh_labels()

    def _label(self, text, cls=None):
        lbl = Gtk.Label(label=text)
        lbl.set_halign(Gtk.Align.START)
        lbl.set_xalign(0.0)
        if cls:
            lbl.get_style_context().add_class(cls)
        return lbl

    # ── Helpers ───────────────────────────────────────────────────────────

    def current_image(self):
        if self.images:
            return self.images[self.current_index]
        return None

    def current_path(self):
        if self.paths:
            return self.paths[self.current_index]
        return None

    def set_status(self, text):
        self.status_var.set_text(text)

    def _refresh_labels(self):
        self.lbl_ratio.set_text(
            f"Rasio: {self.output_width_mm}:{self.output_height_mm}"
        )
        w, h = self.get_output_px()
        self.lbl_output_px.set_text(
            f"Output: {w} x {h} px  (@{self.dpi} DPI)"
        )

    def get_output_px(self):
        w = int(self.output_width_mm * self.dpi / 25.4)
        h = int(self.output_height_mm * self.dpi / 25.4)
        return w, h

    # ── Event handlers ────────────────────────────────────────────────────

    def _on_pick(self, widget):
        dlg = Gtk.FileChooserNative(
            title="Pilih Foto",
            transient_for=self.window,
            action=Gtk.FileChooserAction.OPEN,
        )
        filt = Gtk.FileFilter()
        filt.set_name("Image Files")
        filt.add_pattern("*.png")
        filt.add_pattern("*.jpg")
        filt.add_pattern("*.jpeg")
        filt.add_pattern("*.bmp")
        filt.add_pattern("*.gif")
        filt.add_pattern("*.webp")
        filt.add_pattern("*.tif")
        filt.add_pattern("*.tiff")
        dlg.add_filter(filt)
        dlg.set_select_multiple(True)

        if dlg.run() == Gtk.ResponseType.ACCEPT:
            self.load_paths([Path(p) for p in dlg.get_filenames()])
        dlg.destroy()

    def load_paths(self, paths):
        self.set_status("Memuat gambar...")
        added = 0
        for p in paths:
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file(str(p))
                self.images.append(pb)
                self.paths.append(p)
                added += 1
            except Exception as e:
                print(f"Gagal memuat {p.name}: {e}")

        if added:
            self.current_index = len(self.paths) - 1
            self._rebuild_thumbnails()
            self.canvas.refresh()
            self.canvas.queue_draw()

        self.lbl_count.set_text(f"{len(self.paths)} foto dipilih")
        self.set_status(f"Memuat {added} foto. Total: {len(self.paths)} foto.")

    def _on_preset(self, combo):
        idx = combo.get_active()
        if idx < 0:
            return
        _, w, h = PRESETS[idx]
        if w is not None:
            self.output_width_mm = w
            self.output_height_mm = h
            self.entry_w.set_text(str(w))
            self.entry_h.set_text(str(h))
            self._apply_size()

    def _on_apply_size(self, widget):
        self._apply_size()

    def _apply_size(self):
        try:
            w = int(self.entry_w.get_text().strip())
            h = int(self.entry_h.get_text().strip())
            if w <= 0 or h <= 0:
                raise ValueError
            self.output_width_mm = w
            self.output_height_mm = h
        except ValueError:
            pass
        # pasang crop box baru di tengah
        self.canvas.place_default_crop()
        self.canvas.queue_draw()
        self._refresh_labels()

    def _on_format(self, combo):
        self.format = combo.get_active_text()
        self._refresh_labels()

    def _on_dpi(self, combo):
        self.dpi = int(combo.get_active_text())
        self._refresh_labels()

    def _on_quality(self, scale):
        self.quality = int(scale.get_value())
        self.lbl_quality.set_text(f"{self.quality}%")

    def _on_remove(self, widget):
        if not self.paths:
            return
        idx = self.current_index
        self.images.pop(idx)
        self.paths.pop(idx)
        self.lbl_count.set_text(f"{len(self.paths)} foto dipilih")
        if not self.paths:
            self.canvas.crop = None
            self.canvas._photo = None
            self.canvas._display_key = None
            self._rebuild_thumbnails()
            self.canvas.queue_draw()
            return
        self.current_index = min(idx, len(self.paths) - 1)
        self._rebuild_thumbnails()
        self.canvas.refresh()
        self.canvas.queue_draw()

    def nav_image(self, delta):
        if not self.paths:
            return
        self.current_index = (self.current_index + delta) % len(self.paths)
        self.canvas.refresh()
        self.canvas.queue_draw()
        self._rebuild_thumbnails()

    def _on_key(self, widget, ev):
        if ev.keyval in (Gdk.KEY_Left, Gdk.KEY_KP_Left):
            self.nav_image(-1)
            return True
        if ev.keyval in (Gdk.KEY_Right, Gdk.KEY_KP_Right):
            self.nav_image(1)
            return True
        if ev.keyval == Gdk.KEY_Delete:
            self._on_remove(None)
            return True
        return False

    # ── Thumbnails ────────────────────────────────────────────────────────

    def _rebuild_thumbnails(self):
        for child in self.thumb_box.get_children():
            self.thumb_box.remove(child)
        if not self.images:
            return

        for i, pb in enumerate(self.images):
            thumb = pb.scale_simple(96, 96, GdkPixbuf.InterpType.BILINEAR)
            ev = Gtk.EventBox()
            img = Gtk.Image.new_from_pixbuf(thumb)
            ev.add(img)
            ev.set_border_width(int(2))
            if i == self.current_index:
                ev.set_state_flags(Gtk.StateFlags.SELECTED, clear=False)
                ctx = ev.get_style_context()
                ctx.add_class("thumb-selected")
            ev.connect("button-press-event", self._on_thumb_click, i)
            ev.set_tooltip_text(f"{self.paths[i].name}")
            self.thumb_box.add(ev)
        self.thumb_box.show_all()

    def _on_thumb_click(self, widget, ev, idx):
        self.current_index = idx
        self.canvas.refresh()
        self.canvas.queue_draw()
        self._rebuild_thumbnails()
        return True

    # ── Crop / Export logic ───────────────────────────────────────────────

    def crop_pixbuf_to_pil(self, pb):
        """Konversi area crop (display coords) menjadi PIL image cropped."""
        if self.canvas.crop is None:
            return None
        x1, y1, x2, y2 = self.canvas.crop
        ox, oy = self.canvas.off_x, self.canvas.off_y
        s = self.canvas.scale

        ox1 = max(0, (x1 - ox) / s)
        oy1 = max(0, (y1 - oy) / s)
        ox2 = min(pb.get_width(), (x2 - ox) / s)
        oy2 = min(pb.get_height(), (y2 - oy) / s)

        if ox2 - ox1 < 1 or oy2 - oy1 < 1:
            return None

        # PIL dari raw bytes pixbuf
        rgb = pb.get_pixels()
        w, h, rowstride = pb.get_width(), pb.get_height(), pb.get_rowstride()
        channels = pb.get_n_channels()
        if channels == 4:
            img = Image.frombuffer("RGBA", (w, h), rgb, "raw", "RGBA", rowstride, 1)
            img = img.convert("RGB")
        else:
            img = Image.frombuffer("RGB", (w, h), rgb, "raw", "RGB", rowstride, 1)

        return img.crop((int(ox1), int(oy1), int(ox2), int(oy2)))

    def _on_preview(self, widget):
        if not self.paths:
            self._warn("Pilih foto terlebih dahulu!")
            return
        if self.canvas.crop is None:
            self._warn("Atur area crop terlebih dahulu!")
            return

        win = Gtk.Window(title="Preview Hasil Crop")
        win.set_default_size(900, 700)
        win.set_transient_for(self.window)

        sw = Gtk.ScrolledWindow()
        win.add(sw)
        grid = Gtk.Grid()
        grid.set_column_spacing(16)
        grid.set_row_spacing(16)
        grid.set_margin_top(16)
        grid.set_margin_bottom(16)
        grid.set_margin_start(16)
        grid.set_margin_end(16)
        sw.add(grid)

        ow, oh = self.get_output_px()

        for i, pb in enumerate(self.images):
            cropped = self.crop_pixbuf_to_pil(pb)
            if cropped is None:
                continue
            resized = cropped.resize((ow, oh), Image.LANCZOS)
            rgba = resized.convert("RGBA")
            data = rgba.tobytes("raw", "RGBA")
            thumb = GdkPixbuf.Pixbuf.new_from_bytes(
                GLib.Bytes(data),
                GdkPixbuf.Colorspace.RGB,
                True, 8,
                ow, oh,
                ow * 4,
            )
            # tampilkan tidak penuh ukuran asli
            disp = thumb.scale_simple(
                min(ow, 240), min(oh, 300),
                GdkPixbuf.InterpType.BILINEAR,
            )
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            img = Gtk.Image.new_from_pixbuf(disp)
            box.pack_start(img, False, False, 0)
            lbl = Gtk.Label(label=self.paths[i].name)
            lbl.get_style_context().add_class("muted")
            box.pack_start(lbl, False, False, 0)
            col = i % 3
            row = i // 3
            grid.attach(box, col, row, 1, 1)

        sw.show_all()
        win.show_all()

    def _on_export(self, widget):
        if not self.paths:
            self._warn("Pilih foto terlebih dahulu!")
            return
        if self.canvas.crop is None:
            self._warn("Atur area crop terlebih dahulu!")
            return

        dlg = Gtk.FileChooserNative(
            title="Pilih Folder Untuk Menyimpan",
            transient_for=self.window,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        if dlg.run() != Gtk.ResponseType.ACCEPT:
            dlg.destroy()
            return
        out_dir = Path(dlg.get_filename())
        dlg.destroy()

        ow, oh = self.get_output_px()
        ext, fmt = EXPORT_EXT[self.format]
        save_opts = {"dpi": (self.dpi, self.dpi)}
        if fmt in ("jpeg", "webp"):
            save_opts["quality"] = self.quality
            save_opts["optimize"] = True
        if fmt == "png":
            save_opts = {}

        self.set_status("Mengekspor...")
        while Gtk.events_pending():
            Gtk.main_iteration()

        count = 0
        failed = []
        for i, pb in enumerate(self.images):
            cropped = self.crop_pixbuf_to_pil(pb)
            if cropped is None:
                failed.append(self.paths[i].name)
                continue
            result = cropped.resize((ow, oh), Image.LANCZOS)
            stem = self.paths[i].stem
            out_file = out_dir / f"{stem}_cropped{ext}"
            c = 1
            while out_file.exists():
                out_file = out_dir / f"{stem}_cropped_{c}{ext}"
                c += 1

            try:
                result.save(str(out_file), format=fmt, **save_opts)
                count += 1
            except Exception as e:
                failed.append(self.paths[i].name + f" ({e})")
            self.set_status(f"Mengekspor {count + len(failed)}/{len(self.images)}...")
            while Gtk.events_pending():
                Gtk.main_iteration()

        msg = (f"Berhasil mengekspor {count} foto!\n\n"
               f"Ukuran: {self.output_width_mm}x{self.output_height_mm} mm "
               f"({ow}x{oh}px @ {self.dpi} DPI)\n"
               f"Format: {self.format}\n"
               f"Folder: {out_dir.name}")
        if failed:
            msg += f"\n\nGagal: {len(failed)} → {', '.join(failed[:5])}"
        self.set_status(f"Selesai! {count} foto diekspor.")
        self._info(msg)

    def _warn(self, text):
        dlg = Gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.OK,
            text=text,
        )
        dlg.run()
        dlg.destroy()

    def _info(self, text):
        dlg = Gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=text,
        )
        dlg.run()
        dlg.destroy()


def main():
    Theme.apply()
    app = PhotoCropperApp()
    Gtk.main()


if __name__ == "__main__":
    main()