#!/usr/bin/env python3
"""
Shogi Puzzle Trainer — Optimized Single-file PySide6 application.
Key features:
- SQLite/DuckDB-backed DataProvider for fast puzzle loads
- Paginated puzzle list with Rating/Theme filtering
- Interactive puzzle solving with auto-play opponent responses (USI moves)
- Batch video export of puzzle solutions with explicit timeline control
"""
import sys, os, re, ast, base64, json, csv, math, time, wave, logging
import shutil, subprocess, tempfile, threading, sqlite3
from pathlib import Path
from datetime import datetime
import numpy as np

try:
    import shogi
    HAS_SHOGI = True
except ImportError:
    HAS_SHOGI = False
    print("ERROR: 'shogi' library is required. Install it via: pip install shogi")

from contextlib import contextmanager
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QListWidget, QListWidgetItem,
    QSlider, QComboBox, QCheckBox, QGroupBox, QSplitter,
    QStatusBar, QLineEdit, QProgressBar, QSpinBox, QFileDialog,
    QTabWidget, QScrollArea, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QDialog, QDialogButtonBox,
    QToolTip, QFrame, QGridLayout, QSizePolicy, QToolButton, QDoubleSpinBox
)
from PySide6.QtCore import (
    Qt, QTimer, Signal, QThread, QUrl, QRect, QRectF, QPointF,
    QSortFilterProxyModel, QAbstractTableModel, QModelIndex,
)
from PySide6.QtGui import (
    QPainter, QPixmap, QPalette, QColor, QFont, QPen, QBrush,
    QRadialGradient, QLinearGradient, QImage, QPolygonF, QPainterPath,
    QTransform, QAction, QIcon, QFontMetrics,
)

# ═══════════════════════════════════════════════════════════════════════════════
#  OPTIONAL DEPENDENCIES
# ═══════════════════════════════════════════════════════════════════════════════
HAS_NUMPY = True
HAS_IMAGEIO = False
try:
    import imageio.v3 as iio; HAS_IMAGEIO = True
except Exception: pass

HAS_PANDAS = False; HAS_PYARROW = False; HAS_DUCKDB = False
try:
    import pandas as pd; HAS_PANDAS = True
except ImportError: pass
if not HAS_PANDAS:
    try:
        import pyarrow.parquet as pq; HAS_PYARROW = True
    except ImportError: pass
try:
    import duckdb; HAS_DUCKDB = True
except ImportError: pass

HAS_FFMPEG = shutil.which('ffmpeg') is not None

# ═══════════════════════════════════════════════════════════════════════════════
#  LOGGING
# ═══════════════════════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s.%(msecs)03d] [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

def log(msg, level="INFO"):
    level_map = {
        "INFO": logging.INFO, "WARN": logging.WARNING, "WARNING": logging.WARNING,
        "ERROR": logging.ERROR, "DATA": logging.INFO, "DEBUG": logging.DEBUG
    }
    logger.log(level_map.get(level.upper(), logging.INFO), msg)

# ═══════════════════════════════════════════════════════════════════════════════
#  FILE PATHS
# ═══════════════════════════════════════════════════════════════════════════════
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
EXPORT_DIR = os.path.join(APP_DIR, "exports")
DB_PUZZLES_PATH = os.path.join(DATA_DIR, "shogi_puzzles.parquet")
EXPORT_MANIFEST_PATH = os.path.join(APP_DIR, "export_manifest.json")
SQLITE_DB_PATH = os.path.join(DATA_DIR, "puzzles.db")

# ═══════════════════════════════════════════════════════════════════════════════
#  BOARD / RENDERING CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════
SQ_SIZE   = 64
BOARD_PX  = SQ_SIZE * 9  # 9x9 Shogi board
FILES_STR = '987654321'  # Right to left for Sente
RANKS_STR = '123456789'  # Top to bottom

PIECE_KANJI = {
    shogi.PAWN: '歩', shogi.LANCE: '香', shogi.KNIGHT: '桂', shogi.SILVER: '銀',
    shogi.GOLD: '金', shogi.BISHOP: '角', shogi.ROOK: '飛', shogi.KING: '王'
}
PROMOTED_KANJI = {
    shogi.PAWN: 'と', shogi.LANCE: '杏', shogi.KNIGHT: '圭', shogi.SILVER: '全',
    shogi.BISHOP: '馬', shogi.ROOK: '龍'
}

ANIM_SPEED_SLOW    = 600
ANIM_SPEED_DEFAULT = 300
ANIM_SPEED_FAST    = 120
ANIM_FPS           = 60

# ═══════════════════════════════════════════════════════════════════════════════
#  ARROW STYLES
# ═══════════════════════════════════════════════════════════════════════════════
ARROW_STYLE_SIMPLE  = "simple"
ARROW_STYLE_THICK   = "thick"
ARROW_STYLE_FANCY   = "fancy"
ARROW_STYLE_MINIMAL = "minimal"
ARROW_STYLE_NONE    = "none"
ARROW_STYLES = {
    "Thick": ARROW_STYLE_THICK, "Fancy": ARROW_STYLE_FANCY,
    "Simple": ARROW_STYLE_SIMPLE, "Minimal": ARROW_STYLE_MINIMAL, "None": ARROW_STYLE_NONE,
}
ARROW_STYLES_LIST = list(ARROW_STYLES.keys())

# ═══════════════════════════════════════════════════════════════════════════════
#  BOARD THEMES (Shogi-style — wood board, grid lines, pentagonal pieces)
# ═══════════════════════════════════════════════════════════════════════════════
class BoardTheme:
    def __init__(self, name="Classic",
                 board_bg=(222, 184, 135),
                 grid_color=(80, 55, 25),
                 border=(70, 45, 15),
                 highlight=(255, 255, 0, 100),
                 last_move=(155, 199, 0, 80),
                 arrow=(220, 50, 47, 200),
                 arrow_style=ARROW_STYLE_THICK,
                 piece_bg_sente=(255, 240, 200),
                 piece_bg_gote=(235, 215, 170),
                 piece_border=(90, 58, 20),
                 piece_text=(20, 20, 20),
                 piece_text_promo=(195, 0, 0),
                 promo_zone_tint=(0, 0, 0, 10),
                 star_dot=(80, 55, 25)):
        self.name = name
        self.board_bg = QColor(*board_bg)
        self.grid_color = QColor(*grid_color)
        self.border = QColor(*border)
        self.highlight = QColor(*highlight)
        self.last_move = QColor(*last_move)
        self.arrow_clr = QColor(*arrow)
        self.arrow_style = arrow_style
        self.piece_bg_sente = piece_bg_sente
        self.piece_bg_gote = piece_bg_gote
        self.piece_border = QColor(*piece_border)
        self.piece_text = QColor(*piece_text)
        self.piece_text_promo = QColor(*piece_text_promo)
        self.promo_zone_tint = QColor(*promo_zone_tint) if len(promo_zone_tint) == 4 else QColor(*promo_zone_tint, 10)
        self.star_dot = QColor(*star_dot)
        self.bg = QColor(32, 32, 36)
        self.coord = QColor(140, 110, 70)
        # Backward compat
        self.light_sq = self.board_bg
        self.dark_sq = QColor(self.board_bg).darker(103)

THEMES = {
    "Classic": BoardTheme(),
    "Green":   BoardTheme("Green",
                          board_bg=(194, 178, 128),
                          grid_color=(70, 55, 25),
                          border=(60, 40, 15),
                          piece_bg_sente=(235, 225, 180),
                          piece_bg_gote=(215, 200, 155),
                          piece_border=(80, 55, 20),
                          star_dot=(70, 55, 25)),
    "Dark":    BoardTheme("Dark",
                          board_bg=(115, 90, 55),
                          grid_color=(75, 55, 30),
                          border=(55, 35, 15),
                          piece_bg_sente=(165, 145, 105),
                          piece_bg_gote=(140, 120, 85),
                          piece_border=(55, 35, 15),
                          piece_text=(235, 235, 235),
                          piece_text_promo=(255, 80, 80),
                          coord=(160, 130, 80),
                          star_dot=(75, 55, 30)),
}

# ═══════════════════════════════════════════════════════════════════════════════
#  EXPORT PRESETS
# ═══════════════════════════════════════════════════════════════════════════════
class ExportPreset:
    def __init__(self, name, width, height, fps=30, board_frac=0.82,
                 bg=(26, 26, 46), description=""):
        self.name = name; self.width = width; self.height = height
        self.fps = fps; self.board_frac = board_frac
        self.bg = bg; self.description = description

    @property
    def is_vertical(self): return self.height > self.width
    @property
    def is_square(self): return self.width == self.height
    @property
    def is_board_only(self): return self.board_frac >= 1.0

    def calc_sq_size(self):
        if self.is_vertical:
            board_px = int(self.width * self.board_frac)
        else:
            board_px = int(self.height * 0.78 * self.board_frac / 0.82)
        board_px = (board_px // 9) * 9
        return max(9, board_px // 9)

EXPORT_PRESETS = {
    "YouTube 1080p":    ExportPreset("YouTube 1080p", 1920, 1080, 30, 0.60, (26, 26, 46), "16:9 Full HD"),
    "YouTube 720p":     ExportPreset("YouTube 720p", 1280, 720, 30, 0.60, (26, 26, 46), "16:9 HD"),
    "YouTube Shorts":   ExportPreset("YouTube Shorts", 1080, 1920, 30, 0.70, (26, 26, 46), "9:16 vertical"),
    "Board Only":       ExportPreset("Board Only", 576, 576, 30, 1.00, (26, 26, 46), "Square board-only (9x9)"),
}

# ═══════════════════════════════════════════════════════════════════════════════
#  EXPORT CONFIG
# ═══════════════════════════════════════════════════════════════════════════════
SETTINGS_JSON_PATH = os.path.join(APP_DIR, "settings.json")
class ExportConfig:
    def __init__(self):
        self.fps = 30
        self.title_enabled = True; self.title_duration = 3.0
        self.end_title_enabled = True; self.end_title_duration = 3.0
        self.start_hold_duration = 2.0
        self.end_hold_duration = 2.0
        self.move_anim_duration = 0.5; self.pause_after_move = 0.8
        self.preset_name = "YouTube 1080p"
        self.theme_name = "Classic"
        self.arrow_style = ARROW_STYLE_THICK
        self.ffmpeg_crf = 20; self.ffmpeg_preset = "medium"
        self.title_text_override = ""
        self.end_screen_text = ""
        self.show_logo_watermark = True
        self.flip_board = False
        self._bg_color = None
        self.output_dir = EXPORT_DIR
        self.load()

    def apply_preset(self, name):
        if name in EXPORT_PRESETS:
            p = EXPORT_PRESETS[name]; self.preset_name = name
            self.fps = p.fps

    @property
    def preset(self): return EXPORT_PRESETS.get(self.preset_name, EXPORT_PRESETS["YouTube 1080p"])
    @property
    def target_width(self): return self.preset.width
    @property
    def target_height(self): return self.preset.height
    @property
    def bg_color(self): return self._bg_color if self._bg_color is not None else self.preset.bg
    @bg_color.setter
    def bg_color(self, value): self._bg_color = value
    @property
    def is_vertical(self): return self.preset.is_vertical
    @property
    def sq_size(self): return self.preset.calc_sq_size()

    def save(self):
        try:
            os.makedirs(os.path.dirname(SETTINGS_JSON_PATH), exist_ok=True)
            data = {}
            for k, v in self.__dict__.items():
                if k == '_bg_color': data['bg_color_override'] = list(v) if v is not None else None
                elif not k.startswith('_'):
                    if isinstance(v, Path): v = str(v)
                    data[k] = v
            with open(SETTINGS_JSON_PATH, 'w') as f: json.dump(data, f, indent=2)
        except Exception as e: log(f"Failed to save settings: {e}", "ERROR")

    def load(self):
        if not os.path.exists(SETTINGS_JSON_PATH): return
        try:
            with open(SETTINGS_JSON_PATH, 'r') as f:
                data = json.load(f)
                for k, v in data.items():
                    if k == 'bg_color_override': self._bg_color = tuple(v) if v is not None else None
                    elif hasattr(self, k): setattr(self, k, v)
        except Exception as e: log(f"Failed to load settings: {e}", "WARN")

# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
_SAFE_FS = re.compile(r'[\\/*?:"<>|]')
def _qimage_to_bgr_bytes(img):
    if img.format() != QImage.Format_RGB888:
        img = img.convertToFormat(QImage.Format_RGB888)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    ptr = img.constBits()
    raw = np.frombuffer(ptr, dtype=np.uint8, count=img.sizeInBytes()).reshape((h, bpl)).copy()
    if bpl > w * 3: raw = raw[:, :w * 3]
    return raw.reshape((h, w, 3))[:, :, ::-1].tobytes()

def sanitize_filename(name, max_len=120):
    s = _SAFE_FS.sub('_', name).strip('. ')
    return s[:max_len] if s else "untitled"

def _ease_out_cubic(t): return 1.0 - (1.0 - t) ** 3

def _to_i16(samples):
    return np.clip(samples * 32767.0, -32768, 32767).astype(np.int16)

@contextmanager
def paint_context(image):
    p = QPainter(image)
    try: yield p
    finally:
        if p.isActive(): p.end()

def _make_font(family, size_px, bold=False):
    font = QFont(family, -1, QFont.Bold if bold else QFont.Normal)
    font.setPixelSize(int(size_px))
    return font

# ═══════════════════════════════════════════════════════════════════════════════
#  ENGINE
# ═══════════════════════════════════════════════════════════════════════════════
class ShogiEngine:
    def __init__(self):
        self.board = shogi.Board()
        self.game_over = False; self.result = ""; self.last_move = None

    def reset(self):
        self.board = shogi.Board()
        self.game_over = False; self.result = ""; self.last_move = None

    @staticmethod
    def sq_to_rc(sq): return sq // 9, sq % 9
    @staticmethod
    def rc_to_sq(r, c): return r * 9 + c

    @property
    def turn(self): return 'sente' if self.board.turn == shogi.BLACK else 'gote'

    def check_squares(self):
        if self.board.is_check():
            king_sq = self.board.king(self.board.turn)
            if king_sq is not None: return [self.sq_to_rc(king_sq)]
        return []

    def legal_moves(self, r, c):
        sq = self.rc_to_sq(r, c)
        return [self.sq_to_rc(m.to_square) for m in self.board.legal_moves if m.from_square == sq]

    def make_move(self, fr, fc, tr, tc, promo=None, drop_piece=None):
        if drop_piece:
            to_sq = self.rc_to_sq(tr, tc)
            move = shogi.Move.drop(drop_piece, to_sq)
            if move in self.board.legal_moves:
                notation = self.board.san(move)
                self.board.push(move)
                self.last_move = (None, (tr, tc))
                self.game_over = self.board.is_checkmate()
                self.result = self.board.result() if self.game_over else ""
                return {'from': None, 'to': (tr, tc), 'piece': drop_piece, 'drop': True,
                        'check': self.board.is_check(), 'mate': self.board.is_checkmate(), 'notation': notation}
            return None

        from_sq = self.rc_to_sq(fr, fc)
        to_sq = self.rc_to_sq(tr, tc)
        piece = self.board.piece_at(from_sq)
        if not piece: return None
        
        move = shogi.Move(from_sq, to_sq, promotion=promo if promo else False)
        if move not in self.board.legal_moves: return None
            
        is_promo = move.promotion
        notation = self.board.san(move)
        cap = self.board.piece_at(to_sq)
        captured = cap.symbol() if cap else '.'
        
        piece_obj = shogi.Piece(piece.piece_type, piece.color)
        self.board.push(move)
        self.last_move = ((fr, fc), (tr, tc))
        self.game_over = self.board.is_checkmate()
        self.result = self.board.result() if self.game_over else ""
        
        return {'from': (fr, fc), 'to': (tr, tc), 'piece': piece.symbol(), 'piece_obj': piece_obj,
                'captured': captured, 'promo': is_promo, 'check': self.board.is_check(),
                'mate': self.board.is_checkmate(), 'notation': notation, 'drop': False}

    def make_move_usi(self, usi_str):
        move = shogi.Move.from_usi(usi_str)
        if move in self.board.legal_moves:
            if move.drop:
                return self.make_move(0, 0, *self.sq_to_rc(move.to_square), drop_piece=move.drop)
            else:
                fr, fc = self.sq_to_rc(move.from_square)
                tr, tc = self.sq_to_rc(move.to_square)
                return self.make_move(fr, fc, tr, tc, promo=move.promotion)
        return None

    def undo(self):
        if len(self.board.move_stack) > 0:
            self.board.pop()
            self.game_over = self.board.is_checkmate()
            self.result = self.board.result() if self.game_over else ""
            if self.board.move_stack:
                last = self.board.move_stack[-1]
                if last.drop: self.last_move = (None, self.sq_to_rc(last.to_square))
                else: self.last_move = (self.sq_to_rc(last.from_square), self.sq_to_rc(last.to_square))
            else: self.last_move = None
            return True
        return False

# ═══════════════════════════════════════════════════════════════════════════════
#  PUZZLE SESSION
# ═══════════════════════════════════════════════════════════════════════════════
class PuzzleSession:
    def __init__(self, engine: ShogiEngine):
        self.engine = engine
        self.current_puzzle = None
        self.solution_moves = []
        self.current_move_index = 0

    def load_puzzle(self, puzzle_data):
        self.current_puzzle = puzzle_data
        sfen = puzzle_data.get('sfen', '')
        moves_str = puzzle_data.get('moves', '')
        self.solution_moves = moves_str.split() if moves_str else []
        try:
            self.engine.board = shogi.Board(sfen)
        except ValueError:
            log(f"Invalid SFEN: {sfen}, falling back to start position", "WARN")
            self.engine.board = shogi.Board()
        self.engine.game_over = False
        self.engine.last_move = None
        self.current_move_index = 0

    def try_move_usi(self, usi_str):
        if self.current_move_index >= len(self.solution_moves):
            return "solved", None, None
        expected = self.solution_moves[self.current_move_index]
        if usi_str == expected:
            self.current_move_index += 1
            opp_usi = None
            if self.current_move_index < len(self.solution_moves):
                opp_usi = self.solution_moves[self.current_move_index]
                self.current_move_index += 1
            return "correct", usi_str, opp_usi
        else:
            return "incorrect", None, None
# ═══════════════════════════════════════════════════════════════════════════════
#  RENDERING  — Pentagonal koma, wood-grain board, grid lines
# ═══════════════════════════════════════════════════════════════════════════════
_tl = threading.local()

def get_render_assets(sz):
    isz = int(sz * 100)
    if getattr(_tl, 'cache_sz', -1) == isz:
        return _tl.assets
    font_family = "Yu Mincho, Noto Serif CJK JP, MS Mincho, serif"
    fp = QFont(font_family, int(sz * 0.75))
    fp.setStyleStrategy(QFont.PreferAntialias)
    fc = QFont("Sans", max(7, int(sz * 0.13)), QFont.Bold)
    _tl.assets = (fp, fc)
    _tl.cache_sz = isz
    return _tl.assets

def _set_render_theme(theme):
    _tl.render_theme = theme

def _get_render_theme():
    return getattr(_tl, 'render_theme', THEMES["Classic"])

_piece_cache = {}

def clear_piece_cache():
    _piece_cache.clear()

def _koma_shape(cx, cy, pw, ph, is_sente=True):
    """
    Traditional shogi koma (piece) pentagonal shape.
    For sente the apex points upward (toward opponent).
    For gote the apex points downward (rotated 180°).
    """
    hw = pw / 2
    hh = ph / 2
    path = QPainterPath()
    if is_sente:
        path.moveTo(cx - hw, cy + hh)                  # bottom-left
        path.lineTo(cx + hw, cy + hh)                  # bottom-right
        path.lineTo(cx + hw * 0.72, cy - hh * 0.08)   # right shoulder
        path.lineTo(cx, cy - hh)                        # apex
        path.lineTo(cx - hw * 0.72, cy - hh * 0.08)   # left shoulder
        path.closeSubpath()
    else:
        path.moveTo(cx - hw, cy - hh)                  # top-left
        path.lineTo(cx + hw, cy - hh)                  # top-right
        path.lineTo(cx + hw * 0.72, cy + hh * 0.08)   # right shoulder
        path.lineTo(cx, cy + hh)                        # apex
        path.lineTo(cx - hw * 0.72, cy + hh * 0.08)   # left shoulder
        path.closeSubpath()
    return path


def _draw_piece_at_core(p, piece_obj, row_f, col_f, sz, w, h, font):
    """Draw a pentagonal koma with wood gradient, shadow, and kanji."""
    is_sente = piece_obj.color == shogi.BLACK
    is_promoted = piece_obj.is_promoted

    kanji = (PROMOTED_KANJI.get(piece_obj.piece_type, '?')
             if is_promoted
             else PIECE_KANJI.get(piece_obj.piece_type, '?'))

    theme = _get_render_theme()

    # --- pixel centre of the square the piece sits in ---
    cx = col_f * sz + sz / 2
    cy = row_f * sz + sz / 2

    # piece body size (slightly smaller than cell, respects animation w/h)
    pw = w * 0.82
    ph = h * 0.88

    # 1) Drop shadow
    shadow_off = max(1.5, sz * 0.03)
    shadow_path = _koma_shape(cx + shadow_off, cy + shadow_off, pw, ph, is_sente)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(0, 0, 0, 45))
    p.drawPath(shadow_path)

    # 2) Piece body with wood gradient
    koma_path = _koma_shape(cx, cy, pw, ph, is_sente)
    bg_rgb = theme.piece_bg_sente if is_sente else theme.piece_bg_gote
    grad = QLinearGradient(cx, cy - ph / 2, cx + pw * 0.15, cy + ph / 2)
    grad.setColorAt(0.0, QColor(*bg_rgb).lighter(110))
    grad.setColorAt(0.35, QColor(*bg_rgb))
    grad.setColorAt(1.0, QColor(*bg_rgb).darker(112))

    border_pen = QPen(theme.piece_border, max(1.0, sz * 0.02))
    border_pen.setJoinStyle(Qt.MiterJoin)
    p.setPen(border_pen)
    p.setBrush(QBrush(grad))
    p.drawPath(koma_path)

    # 3) Inner highlight for depth
    inner_path = _koma_shape(cx, cy, pw * 0.91, ph * 0.91, is_sente)
    p.setPen(QPen(QColor(255, 255, 255, 35), max(0.5, sz * 0.007)))
    p.setBrush(Qt.NoBrush)
    p.drawPath(inner_path)

    # 4) Kanji text
    text_color = theme.piece_text_promo if is_promoted else theme.piece_text
    text_path = QPainterPath()
    text_path.addText(QPointF(0, 0), font, kanji)
    br = text_path.boundingRect()
    if br.width() > 0 and br.height() > 0:
        text_path.translate(-br.center().x(), -br.center().y())
        s = min((pw * 0.68) / br.width(), (ph * 0.55) / br.height())
        text_path = QTransform.fromScale(s, s).map(text_path)
        # shift text slightly toward the flat end of the koma
        y_off = ph * 0.04 if is_sente else -ph * 0.04
        text_path.translate(cx, cy + y_off)
    # subtle outline for readability
    p.setPen(QPen(text_color.darker(160), max(0.5, sz * 0.012),
                  Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(text_color)
    p.drawPath(text_path)


def get_cached_piece(piece_obj, sz, font):
    key = (piece_obj.piece_type, piece_obj.color, piece_obj.is_promoted, sz,
           _get_render_theme().name)
    if key not in _piece_cache:
        pixmap = QPixmap(sz, sz)
        pixmap.fill(Qt.transparent)
        with paint_context(pixmap) as p:
            p.setRenderHint(QPainter.Antialiasing)
            p.setRenderHint(QPainter.TextAntialiasing)
            _draw_piece_at_core(p, piece_obj, 0.0, 0.0, sz, sz, sz, font)
        _piece_cache[key] = pixmap
    return _piece_cache[key]


def _draw_piece(p, piece_obj, row, col, sz, font):
    pixmap = get_cached_piece(piece_obj, sz, font)
    p.drawPixmap(int(col * sz), int(row * sz), pixmap)


def _draw_piece_at(p, piece_obj, row_f, col_f, sz, w, h, font):
    _draw_piece_at_core(p, piece_obj, row_f, col_f, sz, w, h, font)


def _draw_arrow(painter, fx, fy, tx, ty, color, sz, style=ARROW_STYLE_THICK):
    if style == ARROW_STYLE_NONE:
        return
    dx, dy = tx - fx, ty - fy
    dist = max(1, math.hypot(dx, dy))
    margin = sz * 0.22
    fx2, fy2 = fx + dx * margin / dist, fy + dy * margin / dist
    tx2, ty2 = tx - dx * margin / dist, ty - dy * margin / dist

    painter.setPen(QPen(color, max(2, sz // 20), Qt.SolidLine, Qt.RoundCap))
    painter.drawLine(int(fx2), int(fy2), int(tx2), int(ty2))

    angle = math.atan2(dy, dy) ; a_sz = sz * 0.22
    p1x = tx2 - a_sz * math.cos(angle - 0.45)
    p1y = ty2 - a_sz * math.sin(angle - 0.45)
    p2x = tx2 - a_sz * math.cos(angle + 0.45)
    p2y = ty2 - a_sz * math.sin(angle + 0.45)
    tri = QPolygonF([QPointF(tx2, ty2), QPointF(p1x, p1y), QPointF(p2x, p2y)])
    painter.setBrush(color); painter.setPen(Qt.NoPen); painter.drawPolygon(tri)


def render_board_image(board, last_move=None, selected=None, legal_targets=None,
                       check_squares=None, anim_state=None, sq_size=SQ_SIZE,
                       show_arrow=True, theme=None, flipped=False, arrow_style=None,
                       static_only=False):
    if theme is None:
        theme = THEMES["Classic"]
    _set_render_theme(theme)

    sz = sq_size
    img = QImage(sz * 9, sz * 9, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)

    with paint_context(img) as p:
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        (font_piece, font_coord) = get_render_assets(sz)

        check_set = set(check_squares or [])
        skip_sq = set()
        if anim_state:
            if anim_state.get('from'):
                skip_sq.add(anim_state['from'])
            skip_sq.add(anim_state['to'])

        b2s = (lambda br, bc: (8 - br, 8 - bc)) if flipped else (lambda br, bc: (br, bc))
        effective_move = anim_state if anim_state else last_move

        # ── 1. Board background (uniform wood) ──────────────────────────
        p.fillRect(0, 0, sz * 9, sz * 9, theme.board_bg)

        # Subtle grain lines
        p.setPen(QPen(QColor(0, 0, 0, 8), max(1, sz * 0.006)))
        for gy in range(0, sz * 9, max(4, sz // 12)):
            p.drawLine(0, gy, sz * 9, gy)

        # ── 2. Promotion-zone tint ──────────────────────────────────────
        # Sente promo zone: rows 6-8 in board coords (rank 1-3)
        # Gote promo zone: rows 0-2 in board coords (rank 7-9)
        if theme.promo_zone_tint.alpha() > 0:
            for start_row, count in [(0, 3), (6, 3)]:
                for dr in range(count):
                    br = start_row + dr
                    for bc in range(9):
                        sr, sc = b2s(br, bc)
                        p.fillRect(sc * sz, sr * sz, sz, sz, theme.promo_zone_tint)

        # ── 3. Highlights (last move, selected, check, legal) ───────────
        for sq in range(81):
            br, bc = sq // 9, sq % 9
            sr, sc = b2s(br, bc)
            x, y = sc * sz, sr * sz

            if effective_move:
                if effective_move[0] and (br, bc) == effective_move[0]:
                    p.fillRect(x, y, sz, sz, theme.last_move)
                if (br, bc) == effective_move[1]:
                    p.fillRect(x, y, sz, sz, theme.last_move)
            if selected and (br, bc) == selected:
                p.fillRect(x, y, sz, sz, theme.highlight)
            if (br, bc) in check_set:
                grad = QRadialGradient(x + sz / 2, y + sz / 2, sz * 0.7)
                grad.setColorAt(0, QColor(255, 30, 30, 180))
                grad.setColorAt(1, QColor(255, 0, 0, 0))
                p.setBrush(QBrush(grad)); p.setPen(Qt.NoPen)
                p.drawRect(x, y, sz, sz)
            if legal_targets and (br, bc) in legal_targets:
                cx_, cy_ = x + sz // 2, y + sz // 2
                p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 80))
                p.drawEllipse(cx_ - sz // 6, cy_ - sz // 6, sz // 3, sz // 3)

        # ── 4. Grid lines ───────────────────────────────────────────────
        grid_pen = QPen(theme.grid_color, max(1, sz * 0.012))
        p.setPen(grid_pen)
        for i in range(10):
            p.drawLine(0, i * sz, 9 * sz, i * sz)   # horizontal
            p.drawLine(i * sz, 0, i * sz, 9 * sz)    # vertical

        # Thick outer border
        border_pen = QPen(theme.border, max(2, sz * 0.035))
        p.setPen(border_pen)
        p.setBrush(Qt.NoBrush)
        p.drawRect(0, 0, sz * 9, sz * 9)

        # ── 5. Star points (hoshi) ──────────────────────────────────────
        # Small dots at the four interior corners of the promotion zones
        dot_r = max(2, int(sz * 0.04))
        p.setPen(Qt.NoPen); p.setBrush(theme.star_dot)
        # Intersections: (3,3), (3,6), (6,3), (6,6) in board coords
        for sr_br, sr_bc in [(3, 3), (3, 6), (6, 3), (6, 6)]:
            sr, sc = b2s(sr_br, sr_bc)
            px_ = sc * sz
            py_ = sr * sz
            p.drawEllipse(px_ - dot_r, py_ - dot_r, dot_r * 2, dot_r * 2)

        # ── 6. Static pieces ────────────────────────────────────────────
        for sq in range(81):
            br, bc = sq // 9, sq % 9
            if (br, bc) in skip_sq:
                continue
            piece = board.piece_at(sq)
            if piece:
                sr, sc = b2s(br, bc)
                _draw_piece(p, piece, sr, sc, sz, font_piece)

        if not static_only:
            # ── 7. Animated piece ───────────────────────────────────────
            if anim_state:
                bfrom = anim_state.get('from')
                bto = anim_state['to']
                btr, btc = bto
                t = anim_state['progress']
                anim_obj = anim_state.get('piece_obj')

                if anim_obj:
                    if bfrom is None:
                        # Drop animation
                        scale = 0.5 + 0.5 * t
                        alpha = int(255 * t)
                        p.setOpacity(alpha / 255.0)
                        sir, sic = b2s(btr, btc)
                        _draw_piece_at(p, anim_obj, sir, sic, sz,
                                       sz * scale, sz * scale, font_piece)
                        p.setOpacity(1.0)
                    else:
                        bfr, bfc = bfrom
                        lift = 4.0 * t * (1.0 - t) * 0.20
                        scale = 1.0 + 4.0 * t * (1.0 - t) * 0.12
                        ir = bfr + (btr - bfr) * t
                        ic = bfc + (btc - bfc) * t
                        sir, sic = b2s(ir, ic)

                        # animation shadow
                        shadow_w = sz * 0.6 * scale
                        shadow_h = sz * 0.10 * scale
                        sa = 30 + int(70 * (lift / 0.20))
                        p.setPen(Qt.NoPen)
                        p.setBrush(QColor(0, 0, 0, sa))
                        pcx = sic * sz + sz / 2
                        p.drawEllipse(QRectF(pcx - shadow_w / 2 + sz * 0.04 * scale,
                                             sir * sz + sz * 0.85,
                                             shadow_w, shadow_h))

                        _draw_piece_at(p, anim_obj,
                                       sir - lift, sic, sz,
                                       sz * scale, sz * scale, font_piece)

            # ── 8. Arrow ────────────────────────────────────────────────
            if show_arrow and effective_move and effective_move[0] is not None:
                (bfr, bfc), (btr, btc) = effective_move
                sfr, sfc = b2s(bfr, bfc)
                str_, stc = b2s(btr, btc)
                _draw_arrow(p, sfc * sz + sz // 2, sfr * sz + sz // 2,
                            stc * sz + sz // 2, str_ * sz + sz // 2,
                            theme.arrow_clr, sz, arrow_style)

        # ── 9. Coordinate labels ────────────────────────────────────────
        p.setFont(font_coord)
        cm = max(3, int(sz * 0.04))
        cs = max(12, sz // 5)
        for c in range(9):
            p.setPen(theme.grid_color.lighter(140))
            file_char = FILES_STR[8 - c if flipped else c]
            p.drawText(QRect(c * sz + sz - cs - cm, 8 * sz + cm, cs, cs),
                       Qt.AlignCenter, file_char)
        for r in range(9):
            p.setPen(theme.grid_color.lighter(140))
            rank_char = RANKS_STR[8 - r if flipped else r]
            p.drawText(QRect(cm, r * sz + cm, cs, cs),
                       Qt.AlignCenter, rank_char)

    return img

class CompositeLayout:
    def __init__(self, width, height, sq_size=None, is_vertical=False, is_square=False, is_board_only=False, show_title=False):
        self.w = width; self.h = height; self.vert = is_vertical; self.show_title = show_title; self.is_board_only = is_board_only
        self.sf = min(width, height) / 1080.0
        if is_board_only: self._board_only_layout(sq_size)
        elif is_vertical: self._vert_layout(sq_size)
        else: self._horiz_layout(sq_size)

    def _make_sq(self, raw_pixels): return max(9, (int(raw_pixels) // 9) * 9)
    
    def _board_only_layout(self, sq_size):
        self.pad = max(4, int(min(self.w, self.h) * 0.01)); self.title_h = 0
        if sq_size is None:
            board_px = min(self.w, self.h) - (self.pad * 2)
            self.sq_size = self._make_sq(board_px / 9)
        else: self.sq_size = sq_size
        self.bpx = self.sq_size * 9
        self.bx = (self.w - self.bpx) // 2; self.by = (self.h - self.bpx) // 2
        self.mx = self.my = self.mw = self.mh = 0

    def _horiz_layout(self, sq_size):
        self.pad = max(8, int(12 * self.sf)); self.title_h = max(44, int(80 * self.sf)) if self.show_title else 0
        gap = self.pad
        min_mw, max_mw = max(180, int(220 * self.sf)), max(280, int(self.w * 0.35))
        target_mw = min(max_mw, max(min_mw, int(280 * self.sf)))
        max_board_w = self.w - target_mw - gap - self.pad * 2
        max_board_h = self.h - self.title_h - self.pad * 3
        if sq_size is None: self.sq_size = self._make_sq(min(max_board_w, max_board_h) / 9)
        else: self.sq_size = max(9, sq_size)
        self.bpx = self.sq_size * 9
        remaining_w = self.w - self.bpx - gap - self.pad * 2
        actual_mw = max(min_mw, min(max_mw, remaining_w)) if remaining_w >= min_mw else max(80, remaining_w)
        total_content_w = self.bpx + gap + actual_mw
        group_x = (self.w - total_content_w) // 2
        vert_space = self.h - self.title_h - self.pad * 2
        board_y = self.title_h + self.pad + max(0, (vert_space - self.bpx) // 2)
        self.bx, self.by = group_x, board_y
        self.mx, self.my, self.mw, self.mh = group_x + self.bpx + gap, board_y, actual_mw, self.bpx

    def _vert_layout(self, sq_size):
        self.pad = max(8, int(14 * self.sf)); self.title_h = max(36, int(50 * self.sf)) if self.show_title else 0
        gap = self.pad
        min_mh, max_mh = max(120, int(150 * self.sf)), max(180, int(self.h * 0.35))
        target_mh = min(max_mh, max(min_mh, int(200 * self.sf)))
        max_board_w = self.w - self.pad * 2
        max_board_h = self.h - self.title_h - target_mh - gap - self.pad * 3
        if sq_size is None: self.sq_size = self._make_sq(min(max_board_w, max_board_h) / 9)
        else: self.sq_size = max(9, sq_size)
        self.bpx = self.sq_size * 9
        remaining_h = self.h - self.title_h - self.bpx - gap - self.pad * 3
        actual_mh = max(min_mh, min(max_mh, remaining_h)) if remaining_h >= min_mh else max(60, remaining_h)
        board_x = (self.w - self.bpx) // 2
        total_content_h = self.bpx + gap + actual_mh
        vert_space = self.h - self.title_h - self.pad * 2
        group_y = self.title_h + self.pad + max(0, (vert_space - total_content_h) // 2)
        self.bx, self.by = board_x, group_y
        self.mx, self.my, self.mw, self.mh = board_x, group_y + self.bpx + gap, self.bpx, actual_mh

def render_composite_frame(board, notations, current_move_idx, last_move=None,
                           check_squares=None, anim_state=None, anim_move_idx=-1,
                           width=1920, height=1080, sq_size=None, theme=None,
                           flipped=False, bg_color=(26, 26, 46), arrow_style=None,
                           is_board_only=False, static_board_img=None):
    if theme is None:
        theme = THEMES["Classic"]
    _set_render_theme(theme)

    is_vert = height > width
    is_sq = (width == height)
    layout = CompositeLayout(width, height, sq_size=sq_size, is_vertical=is_vert,
                             is_square=is_sq, is_board_only=is_board_only,
                             show_title=not is_board_only)
    sq = layout.sq_size
    sf = layout.sf
    img = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(*bg_color))

    with paint_context(img) as p:
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        # Always use render_board_image (handles animation internally)
        board_img = render_board_image(
            board, last_move=last_move, check_squares=check_squares,
            anim_state=anim_state, sq_size=sq, theme=theme,
            flipped=flipped, arrow_style=arrow_style)
        p.drawImage(layout.bx, layout.by, board_img)

        if layout.mw > 20 and layout.mh > 20:
            display_idx = anim_move_idx if anim_move_idx >= 0 else current_move_idx
            _draw_move_list(p, notations, display_idx, layout, bg_color, sf)
    return img

def _draw_move_list(p, notations, current_idx, layout, bg_color, sf):
    mx, my, mw, mh = layout.mx, layout.my, layout.mw, layout.mh
    panel_bg = QColor(*bg_color).lighter(115)
    p.setPen(Qt.NoPen); p.setBrush(panel_bg)
    radius = max(6, int(10 * sf))
    p.drawRoundedRect(QRectF(mx, my, mw, mh), radius, radius)
    
    hdr_h = max(32, int(48 * sf)); hdr_fs = max(14, int(24 * sf))
    p.setFont(QFont("Sans", hdr_fs, QFont.Bold)); p.setPen(QColor(140, 140, 160))
    p.drawText(QRectF(mx + int(16 * sf), my + int(6 * sf), mw - int(32 * sf), hdr_h), Qt.AlignVCenter | Qt.AlignLeft, "MOVES")
    
    sep_y = my + hdr_h + int(6 * sf)
    p.setPen(QPen(QColor(80, 80, 100), max(1.5, 1.5 * sf)))
    p.drawLine(int(mx + int(16 * sf)), int(sep_y), int(mx + mw - int(16 * sf)), int(sep_y))
    
    row_h = max(32, int(44 * sf)); fs = max(16, int(22 * sf))
    move_font = QFont("Monospace", fs); move_font_active = QFont("Monospace", fs, QFont.Bold)
    num_font = QFont("Sans", max(14, int(fs * 0.85)))
    content_y = sep_y + int(8 * sf)
    available_h = my + mh - content_y - int(12 * sf)
    max_rows = max(1, available_h // row_h)
    
    pairs = []
    for i in range(0, len(notations), 2):
        w_move = notations[i] if i < len(notations) else ""
        b_move = notations[i + 1] if i + 1 < len(notations) else ""
        pairs.append((i + 1, w_move, b_move, i, i + 1 if i + 1 < len(notations) else -1))
        
    scroll = 0
    if len(pairs) > max_rows:
        cur_pair = current_idx // 2 if current_idx >= 0 else 0
        scroll = max(0, min(cur_pair - max_rows // 2, len(pairs) - max_rows))
        
    col_num_w = max(32, int(mw * 0.15))
    col_w = (mw - col_num_w - int(24 * sf)) / 2.0
    highlight_clr = QColor(42, 130, 218, 70)
    active_text_clr = QColor(100, 200, 255)
    normal_w_clr, normal_b_clr, num_clr = QColor(230, 230, 230), QColor(190, 190, 200), QColor(120, 120, 140)
    
    for row_i in range(max_rows):
        pi = scroll + row_i
        if pi >= len(pairs): break
        move_num, w_txt, b_txt, w_idx, b_idx = pairs[pi]
        ry = content_y + row_i * row_h
        w_active = (current_idx == w_idx and w_txt)
        b_active = (current_idx == b_idx and b_txt)
        
        if w_active:
            p.setPen(Qt.NoPen); p.setBrush(highlight_clr)
            p.drawRoundedRect(QRectF(mx + col_num_w + int(12 * sf), ry, col_w, row_h - 2), max(3, int(4 * sf)), max(3, int(4 * sf)))
        if b_active:
            p.setPen(Qt.NoPen); p.setBrush(highlight_clr)
            p.drawRoundedRect(QRectF(mx + col_num_w + int(12 * sf) + col_w + int(4 * sf), ry, col_w, row_h - 2), max(3, int(4 * sf)), max(3, int(4 * sf)))
            
        p.setFont(num_font); p.setPen(num_clr)
        p.drawText(QRectF(mx + int(12 * sf), ry, col_num_w, row_h - 2), Qt.AlignVCenter | Qt.AlignRight, f"{move_num}.")
        
        if w_active: p.setFont(move_font_active); p.setPen(active_text_clr)
        else: p.setFont(move_font); p.setPen(normal_w_clr)
        if w_txt: p.drawText(QRectF(mx + col_num_w + int(16 * sf), ry, col_w, row_h - 2), Qt.AlignVCenter | Qt.AlignLeft, w_txt)
        
        if b_active: p.setFont(move_font_active); p.setPen(active_text_clr)
        else: p.setFont(move_font); p.setPen(normal_b_clr)
        if b_txt: p.drawText(QRectF(mx + col_num_w + int(16 * sf) + col_w + int(8 * sf), ry, col_w, row_h - 2), Qt.AlignVCenter | Qt.AlignLeft, b_txt)

def _draw_fitted_text(painter, rect, text, base_font, max_size_px=None, min_size_px=10, flags=Qt.AlignCenter | Qt.TextWordWrap, color=None):
    original_pen = painter.pen()
    if color is not None: painter.setPen(QPen(color))
    family, bold = base_font.family(), base_font.bold()
    min_size_px, max_size_px = int(min_size_px), int(max_size_px or base_font.pixelSize())
    q_rect = QRect(int(rect.x()), int(rect.y()), int(rect.width()), int(rect.height()))
    
    trial_font = _make_font(family, max_size_px, bold)
    painter.setFont(trial_font)
    fm = painter.fontMetrics()
    br = fm.boundingRect(q_rect, int(flags), text)
    if br.width() <= rect.width() and br.height() <= rect.height():
        painter.drawText(rect, int(flags), text); painter.setPen(original_pen); return
        
    scale_w = rect.width() / br.width() if br.width() > 0 else 1.0
    scale_h = rect.height() / br.height() if br.height() > 0 else 1.0
    estimated_size = max(min_size_px, min(max_size_px, int(max_size_px * min(scale_w, scale_h) * 0.92)))
    
    for size in range(estimated_size, min_size_px - 1, -1):
        trial_font = _make_font(family, size, bold)
        painter.setFont(trial_font)
        if painter.fontMetrics().boundingRect(q_rect, int(flags), text).width() <= rect.width():
            painter.drawText(rect, int(flags), text); painter.setPen(original_pen); return
            
    painter.setFont(_make_font(family, min_size_px, bold))
    painter.drawText(rect, int(flags), text); painter.setPen(original_pen)

def render_export_title_card(opening_name, eco, num_moves, width=1920, height=1080, bg_color=(26, 26, 46)):
    img = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(*bg_color))
    with paint_context(img) as p:
        p.setRenderHint(QPainter.Antialiasing); p.setRenderHint(QPainter.TextAntialiasing)
        sf = min(width, height) / 1080.0; margin = max(12, int(60 * sf))
        grad = QLinearGradient(0, 0, 0, height)
        grad.setColorAt(0, QColor(*bg_color).lighter(130)); grad.setColorAt(0.5, QColor(*bg_color)); grad.setColorAt(1, QColor(*bg_color).lighter(110))
        p.fillRect(0, 0, width, height, grad)
        
        p.setPen(Qt.NoPen); p.setBrush(QColor(255, 255, 255, 12))
        wm_font = QFont("Yu Mincho"); wm_font.setPixelSize(max(16, int(480 * sf)))
        p.setFont(wm_font); p.drawText(QRectF(0, 0, width, height), Qt.AlignCenter, "王")
        
        lw = width * 0.4; pen_w = max(1.0, 2.0 * sf); line_y = int(height * 0.45)
        p.setPen(QPen(QColor(100, 100, 140, 120), pen_w))
        p.drawLine(int((width - lw) / 2), line_y, int((width + lw) / 2), line_y)
        
        title_rect = QRectF(margin, height * 0.15, width - 2 * margin, height * 0.25)
        _draw_fitted_text(p, title_rect, opening_name, _make_font("Sans", 64 * sf, bold=True), max_size_px=64*sf, min_size_px=24*sf, flags=Qt.AlignCenter | Qt.TextWordWrap, color=QColor(240, 240, 245))
        
        info = f"Themes: {eco}   ·   {num_moves} half-moves"
        info_rect = QRectF(margin, line_y + int(20 * sf), width - 2 * margin, height * 0.15)
        _draw_fitted_text(p, info_rect, info, _make_font("Sans", 28 * sf), max_size_px=28*sf, min_size_px=16*sf, flags=Qt.AlignCenter | Qt.TextWordWrap, color=QColor(160, 160, 190))
    return img

def render_export_end_screen(opening_name, eco, num_moves, width=1920, height=1080, bg_color=(26, 26, 46)):
    img = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(*bg_color))
    with paint_context(img) as p:
        p.setRenderHint(QPainter.Antialiasing); p.setRenderHint(QPainter.TextAntialiasing)
        sf = min(width, height) / 1080.0; margin = max(12, int(60 * sf))
        grad = QLinearGradient(0, 0, 0, height)
        grad.setColorAt(0, QColor(*bg_color)); grad.setColorAt(0.5, QColor(*bg_color).lighter(120)); grad.setColorAt(1, QColor(*bg_color))
        p.fillRect(0, 0, width, height, grad)
        
        p.setPen(Qt.NoPen); p.setBrush(QColor(255, 255, 255, 8))
        wm_font = QFont("Yu Mincho"); wm_font.setPixelSize(max(16, int(380 * sf)))
        p.setFont(wm_font); p.drawText(QRectF(0, 0, width, height), Qt.AlignCenter, "飛")
        
        thanks_rect = QRectF(margin, height * 0.18, width - 2 * margin, height * 0.12)
        _draw_fitted_text(p, thanks_rect, "Thanks for Watching!", _make_font("Sans", 64 * sf, bold=True), max_size_px=64*sf, min_size_px=32*sf, flags=Qt.AlignCenter | Qt.TextWordWrap, color=QColor(240, 240, 245))
        
        name_text = f"{opening_name}  ·  Themes: {eco}"
        name_rect = QRectF(margin, height * 0.30, width - 2 * margin, height * 0.12)
        _draw_fitted_text(p, name_rect, name_text, _make_font("Sans", 36 * sf), max_size_px=36*sf, min_size_px=20*sf, flags=Qt.AlignCenter | Qt.TextWordWrap, color=QColor(160, 160, 190))
        
        lw = width * 0.35; pen_w = max(1.0, 2.0 * sf); line_y = int(height * 0.48)
        p.setPen(QPen(QColor(100, 100, 140, 100), pen_w))
        p.drawLine(int((width - lw) / 2), line_y, int((width + lw) / 2), line_y)
        
        btn_w, btn_h = max(240, int(360 * sf)), max(48, int(72 * sf))
        btn_x, btn_y = int((width - btn_w) / 2), int(height * 0.56)
        btn_rect = QRectF(btn_x, btn_y, btn_w, btn_h)
        p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 60))
        p.drawRoundedRect(QRectF(btn_x + 2, btn_y + 3, btn_w, btn_h), btn_h / 2.0, btn_h / 2.0)
        p.setBrush(QColor(255, 0, 0)); p.drawRoundedRect(btn_rect, btn_h / 2.0, btn_h / 2.0)
        p.setPen(QColor(255, 255, 255)); p.setFont(QFont("Sans", max(16, int(32 * sf)), QFont.Bold))
        p.drawText(btn_rect, Qt.AlignCenter, "SUBSCRIBE")
        
        like_rect = QRectF(margin, btn_y + btn_h + int(24 * sf), width - 2 * margin, height * 0.08)
        _draw_fitted_text(p, like_rect, "Like if this puzzle helped you!", _make_font("Sans", 26 * sf), max_size_px=26*sf, min_size_px=16*sf, flags=Qt.AlignCenter | Qt.TextWordWrap, color=QColor(140, 160, 200))
    return img

# ═══════════════════════════════════════════════════════════════════════════════
#  SQLITE-BACKED DATA PROVIDER
# ═══════════════════════════════════════════════════════════════════════════════
class DataProvider:
    SCHEMA = '''
    CREATE TABLE IF NOT EXISTS puzzles (
        id          TEXT PRIMARY KEY,
        sfen        TEXT NOT NULL,
        moves       TEXT NOT NULL,
        rating      INTEGER,
        rating_dev  INTEGER,
        popularity  INTEGER,
        nb_plays    INTEGER,
        themes      TEXT,
        game_url    TEXT,
        opening_tags TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_rating ON puzzles(rating);
    CREATE INDEX IF NOT EXISTS idx_popularity ON puzzles(popularity);
    '''
    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self.use_duckdb = HAS_DUCKDB
        self.parquet_path = None
        possible_names = ["shogi_puzzles.parquet", "tsume_shogi.parquet"]
        for name in possible_names:
            path = os.path.join(DATA_DIR, name)
            if os.path.exists(path): self.parquet_path = path; break
            
        if self.use_duckdb and self.parquet_path:
            import duckdb
            self.conn = duckdb.connect(database=':memory:')
            self._total_count = self.conn.execute(f"SELECT COUNT(*) FROM read_parquet('{self.parquet_path}')").fetchone()[0]
            log(f"DataProvider ready (DuckDB): {self._total_count} puzzles", "DATA")
        else:
            self.conn = sqlite3.connect(SQLITE_DB_PATH, check_same_thread=False)
            self.conn.execute("PRAGMA journal_mode=WAL"); self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.execute("PRAGMA cache_size=-64000"); self.conn.execute("PRAGMA temp_store=MEMORY")
            self.conn.row_factory = sqlite3.Row
            self._ensure_schema()
            self._migrate_from_parquet()
            self._total_count = self._get_count()
            log(f"DataProvider ready (SQLite): {self._total_count} puzzles", "DATA")

    def _ensure_schema(self):
        self.conn.executescript(self.SCHEMA); self.conn.commit()

    def _migrate_from_parquet(self):
        if self._get_count() > 0 or not self.parquet_path: return
        log("Migrating puzzles from parquet to SQLite...", "DATA")
        try:
            if HAS_PANDAS:
                import pandas as pd
                df = pd.read_parquet(self.parquet_path)
                df.to_sql('puzzles', self.conn, if_exists='append', index=False, chunksize=50000)
                self.conn.commit()
                log(f"Migration complete: {self._get_count()} puzzles", "DATA")
        except Exception as e: log(f"Migration error: {e}", "ERROR")

    def _get_count(self):
        row = self.conn.execute("SELECT COUNT(*) FROM puzzles").fetchone()
        return row[0] if row else 0

    @property
    def total_puzzles(self): return self._total_count

    def get_page(self, page=0, per_page=50, sort_col="rating", sort_asc=False, min_rating=0, max_rating=4000, theme_filter=""):
        offset = page * per_page; direction = "ASC" if sort_asc else "DESC"
        safe_cols = {"rating", "popularity", "nb_plays", "id"}
        if sort_col not in safe_cols: sort_col = "rating"
        
        if self.use_duckdb:
            query = f"SELECT PuzzleId as id, Rating as rating, Themes as themes, Popularity as popularity FROM read_parquet('{self.parquet_path}') WHERE Rating BETWEEN ? AND ?"
            params = [min_rating, max_rating]
            if theme_filter: query += " AND LOWER(Themes) LIKE LOWER(?)"; params.append(f"%{theme_filter}%")
            query += f" ORDER BY {sort_col} {direction} LIMIT ? OFFSET ?"; params.extend([per_page, offset])
            rows = self.conn.execute(query, params).fetchall()
            rows = [{"id": r[0], "rating": r[1], "themes": r[2], "popularity": r[3]} for r in rows]
            
            count_query = f"SELECT COUNT(*) FROM read_parquet('{self.parquet_path}') WHERE Rating BETWEEN ? AND ?"
            count_params = [min_rating, max_rating]
            if theme_filter: count_query += " AND LOWER(Themes) LIKE LOWER(?)"; count_params.append(f"%{theme_filter}%")
            total = self.conn.execute(count_query, count_params).fetchone()[0]
            return rows, total
        else:
            query = "SELECT id, rating, themes, popularity FROM puzzles WHERE rating BETWEEN ? AND ?"
            params = [min_rating, max_rating]
            if theme_filter: query += " AND themes LIKE ?"; params.append(f"%{theme_filter}%")
            query += f" ORDER BY {sort_col} {direction} LIMIT ? OFFSET ?"; params.extend([per_page, offset])
            rows = self.conn.execute(query, params).fetchall()
            
            count_query = "SELECT COUNT(*) FROM puzzles WHERE rating BETWEEN ? AND ?"
            count_params = [min_rating, max_rating]
            if theme_filter: count_query += " AND themes LIKE ?"; count_params.append(f"%{theme_filter}%")
            total = self.conn.execute(count_query, count_params).fetchone()[0]
            return [dict(r) for r in rows], total

    def get_puzzle(self, puzzle_id):
        if self.use_duckdb:
            row = self.conn.execute(f"SELECT PuzzleId, SFEN, Moves, Rating, RatingDeviation, Popularity, NbPlays, Themes, GameUrl, OpeningTags FROM read_parquet('{self.parquet_path}') WHERE PuzzleId = ?", (puzzle_id,)).fetchone()
            if row: return {'id': row[0], 'sfen': row[1], 'moves': row[2], 'rating': row[3], 'rating_dev': row[4], 'popularity': row[5], 'nb_plays': row[6], 'themes': row[7], 'game_url': row[8], 'opening_tags': row[9]}
            return None
        else:
            row = self.conn.execute("SELECT * FROM puzzles WHERE id = ?", (puzzle_id,)).fetchone()
            return dict(row) if row else None

    def clear_all(self):
        if not self.use_duckdb: self.conn.execute("DELETE FROM puzzles"); self.conn.commit(); self._total_count = 0

    def close(self): self.conn.close()

# ═══════════════════════════════════════════════════════════════════════════════
#  PAGINATED PUZZLES LIST WIDGET
# ═══════════════════════════════════════════════════════════════════════════════
class PaginatedPuzzlesWidget(QWidget):
    puzzle_selected = Signal(str)
    selection_changed = Signal(list)
    PAGE_SIZE = 50

    def __init__(self, data_provider: DataProvider, parent=None):
        super().__init__(parent)
        self.dp = data_provider
        self._current_page = 0; self._total_pages = 1; self._selected_ids = set()
        self._sort_col = "rating"; self._sort_asc = False
        self._min_rating = 0; self._max_rating = 4000; self._theme_filter = ""
        self._build_ui(); self._refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(4)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Rating:"))
        self.spin_min_rating = QSpinBox(); self.spin_min_rating.setRange(0, 4000); self.spin_min_rating.setValue(0); self.spin_min_rating.setFixedWidth(60)
        self.spin_min_rating.valueChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self.spin_min_rating); filter_row.addWidget(QLabel("-"))
        self.spin_max_rating = QSpinBox(); self.spin_max_rating.setRange(0, 4000); self.spin_max_rating.setValue(4000); self.spin_max_rating.setFixedWidth(60)
        self.spin_max_rating.valueChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self.spin_max_rating)
        filter_row.addWidget(QLabel("Theme:"))
        self.edit_theme = QLineEdit(); self.edit_theme.setPlaceholderText("e.g. tsume"); self.edit_theme.setClearButtonEnabled(True)
        self.edit_theme.textChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self.edit_theme)
        layout.addLayout(filter_row)
        
        batch_row = QHBoxLayout()
        self.btn_select_page = QPushButton("Select Page"); self.btn_select_page.setFixedHeight(26)
        self.btn_select_page.setStyleSheet("QPushButton{background:#3a3a4a;color:#ddd;border:none;border-radius:3px;padding:2px 8px;font-size:11px}")
        self.btn_select_page.clicked.connect(self._select_page)
        batch_row.addWidget(self.btn_select_page)
        self.btn_select_none = QPushButton("Clear Sel."); self.btn_select_none.setFixedHeight(26)
        self.btn_select_none.setStyleSheet("QPushButton{background:#3a3a4a;color:#ddd;border:none;border-radius:3px;padding:2px 8px;font-size:11px}")
        self.btn_select_none.clicked.connect(self._select_none)
        batch_row.addWidget(self.btn_select_none)
        self.lbl_selected = QLabel("0 selected"); self.lbl_selected.setStyleSheet("color:#8a8aaa;font-size:11px;")
        batch_row.addWidget(self.lbl_selected); batch_row.addStretch()
        layout.addLayout(batch_row)
        
        sort_row = QHBoxLayout()
        sort_row.addWidget(QLabel("Sort:"))
        self.sort_combo = QComboBox(); self.sort_combo.addItems(["Rating", "Popularity", "Plays", "ID"])
        self.sort_combo.setFixedWidth(80); self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        sort_row.addWidget(self.sort_combo)
        self.btn_sort_dir = QPushButton("↓"); self.btn_sort_dir.setFixedSize(26, 26)
        self.btn_sort_dir.clicked.connect(self._toggle_sort_dir)
        sort_row.addWidget(self.btn_sort_dir); sort_row.addStretch()
        layout.addLayout(sort_row)
        
        self.table = QTableWidget(); self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["☑", "ID", "Rating", "Themes", "Popularity"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 28); self.table.setColumnWidth(1, 60); self.table.setColumnWidth(2, 60); self.table.setColumnWidth(4, 70)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False); self.table.setShowGrid(False); self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("""
            QTableWidget { background-color: #1e1e2a; alternate-background-color: #22223a; color: #ddd; font-size: 12px; border: 1px solid #333; gridline-color: #2a2a3a; }
            QTableWidget::item { padding: 3px 4px; } QTableWidget::item:selected { background: #2a82da; }
            QHeaderView::section { background: #16162a; color: #9a9abc; font-weight: bold; font-size: 11px; padding: 4px; border: none; border-bottom: 1px solid #333; }
        """)
        self.table.cellClicked.connect(self._on_cell_clicked)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        layout.addWidget(self.table, 1)
        
        page_row = QHBoxLayout()
        self.btn_first = QPushButton("⏮"); self.btn_prev = QPushButton("◀")
        self.lbl_page = QLabel("Page 1/1")
        self.btn_next = QPushButton("▶"); self.btn_last = QPushButton("⏭")
        for btn in (self.btn_first, self.btn_prev, self.btn_next, self.btn_last):
            btn.setFixedSize(30, 26)
            btn.setStyleSheet("QPushButton{background:#2a2a3a;color:#ccc;border:1px solid #444;border-radius:3px}")
            page_row.addWidget(btn)
        self.lbl_page.setStyleSheet("color:#9a9abc;font-size:11px;padding:0 6px;")
        page_row.addWidget(self.lbl_page); page_row.addStretch()
        self.lbl_total = QLabel("0 puzzles"); self.lbl_total.setStyleSheet("color:#6a6a8a;font-size:11px;")
        page_row.addWidget(self.lbl_total)
        layout.addLayout(page_row)
        
        self.btn_first.clicked.connect(lambda: self._goto_page(0))
        self.btn_prev.clicked.connect(lambda: self._goto_page(self._current_page - 1))
        self.btn_next.clicked.connect(lambda: self._goto_page(self._current_page + 1))
        self.btn_last.clicked.connect(lambda: self._goto_page(self._total_pages - 1))

    def _on_filter_changed(self):
        self._min_rating = self.spin_min_rating.value(); self._max_rating = self.spin_max_rating.value()
        self._theme_filter = self.edit_theme.text().strip(); self._current_page = 0; self._refresh()

    def _refresh(self):
        rows, count = self.dp.get_page(self._current_page, self.PAGE_SIZE, self._sort_col, self._sort_asc, self._min_rating, self._max_rating, self._theme_filter)
        self._total_pages = max(1, (count + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        self._populate_table(rows); self._update_pagination(count); self._update_selection_label()

    def _populate_table(self, rows):
        self.table.setRowCount(len(rows))
        for i, rec in enumerate(rows):
            pid = rec['id']
            chk_item = QTableWidgetItem(); chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk_item.setCheckState(Qt.Checked if pid in self._selected_ids else Qt.Unchecked)
            chk_item.setData(Qt.UserRole, pid); self.table.setItem(i, 0, chk_item)
            
            id_item = QTableWidgetItem(pid); id_item.setData(Qt.UserRole, pid); self.table.setItem(i, 1, id_item)
            rating_item = QTableWidgetItem(str(rec.get('rating', 0))); rating_item.setData(Qt.UserRole, pid); self.table.setItem(i, 2, rating_item)
            themes_item = QTableWidgetItem(rec.get('themes', '')); themes_item.setData(Qt.UserRole, pid); themes_item.setToolTip(rec.get('themes', '')); self.table.setItem(i, 3, themes_item)
            pop_item = QTableWidgetItem(str(rec.get('popularity', 0))); pop_item.setData(Qt.UserRole, pid); self.table.setItem(i, 4, pop_item)
        self.table.resizeRowsToContents()

    def _update_pagination(self, count):
        self.lbl_page.setText(f"Page {self._current_page + 1}/{self._total_pages}")
        self.lbl_total.setText(f"{count} puzzles")
        self.btn_first.setEnabled(self._current_page > 0); self.btn_prev.setEnabled(self._current_page > 0)
        self.btn_next.setEnabled(self._current_page < self._total_pages - 1); self.btn_last.setEnabled(self._current_page < self._total_pages - 1)

    def _on_cell_clicked(self, row, col):
        item = self.table.item(row, 0)
        if not item: return
        pid = item.data(Qt.UserRole)
        if col == 0:
            if pid in self._selected_ids: self._selected_ids.discard(pid); item.setCheckState(Qt.Unchecked)
            else: self._selected_ids.add(pid); item.setCheckState(Qt.Checked)
            self._update_selection_label(); self.selection_changed.emit(list(self._selected_ids))
        else: self.puzzle_selected.emit(pid)

    def _on_cell_double_clicked(self, row, col):
        item = self.table.item(row, 0)
        if item: self.puzzle_selected.emit(item.data(Qt.UserRole))

    def _on_sort_changed(self, idx):
        col_map = {0: "rating", 1: "popularity", 2: "nb_plays", 3: "id"}
        self._sort_col = col_map.get(idx, "rating"); self._current_page = 0; self._refresh()

    def _toggle_sort_dir(self):
        self._sort_asc = not self._sort_asc; self.btn_sort_dir.setText("↑" if self._sort_asc else "↓")
        self._current_page = 0; self._refresh()

    def _goto_page(self, page):
        page = max(0, min(page, self._total_pages - 1))
        if page != self._current_page: self._current_page = page; self._refresh()

    def _select_page(self):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item: pid = item.data(Qt.UserRole); self._selected_ids.add(pid); item.setCheckState(Qt.Checked)
        self._update_selection_label(); self.selection_changed.emit(list(self._selected_ids))

    def _select_none(self):
        self._selected_ids.clear(); self._sync_checkboxes(); self._update_selection_label(); self.selection_changed.emit([])

    def _sync_checkboxes(self):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item: pid = item.data(Qt.UserRole); item.setCheckState(Qt.Checked if pid in self._selected_ids else Qt.Unchecked)

    def _update_selection_label(self): self.lbl_selected.setText(f"{len(self._selected_ids)} selected")
    def get_selected_ids(self): return list(self._selected_ids)

# ═══════════════════════════════════════════════════════════════════════════════
#  PREVIEW WIDGET
# ═══════════════════════════════════════════════════════════════════════════════
class PreviewWidget(QWidget):
    def __init__(self, export_config: ExportConfig, parent=None):
        super().__init__(parent)
        self.config = export_config; self._opening_name = ""; self._eco = ""; self._num_moves = 0
        self._title_img = None; self._end_img = None; self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self); layout.setContentsMargins(4, 4, 4, 4); layout.setSpacing(4)
        title_lbl = QLabel("TITLE CARD PREVIEW"); title_lbl.setStyleSheet("color:#7a7a9a;font-size:10px;font-weight:bold;")
        layout.addWidget(title_lbl)
        self.title_canvas = QLabel(); self.title_canvas.setFixedSize(240, 135); self.title_canvas.setAlignment(Qt.AlignCenter)
        self.title_canvas.setStyleSheet("QLabel{background:#1a1a2e;border:1px solid #333;border-radius:4px;}")
        layout.addWidget(self.title_canvas, 0, Qt.AlignCenter)
        end_lbl = QLabel("END SCREEN PREVIEW"); end_lbl.setStyleSheet("color:#7a7a9a;font-size:10px;font-weight:bold;")
        layout.addWidget(end_lbl)
        self.end_canvas = QLabel(); self.end_canvas.setFixedSize(240, 135); self.end_canvas.setAlignment(Qt.AlignCenter)
        self.end_canvas.setStyleSheet("QLabel{background:#1a1a2e;border:1px solid #333;border-radius:4px;}")
        layout.addWidget(self.end_canvas, 0, Qt.AlignCenter)
        layout.addStretch()
        self.btn_regen = QPushButton("Refresh Preview")
        self.btn_regen.setStyleSheet("QPushButton{background:#2a2a3a;color:#ccc;border:1px solid #444;border-radius:3px;padding:4px 8px}")
        self.btn_regen.clicked.connect(self._regenerate); layout.addWidget(self.btn_regen)

    def set_opening(self, name, eco, num_moves):
        self._opening_name = name; self._eco = eco; self._num_moves = num_moves; self._regenerate()

    def _regenerate(self):
        pw, ph = self.config.target_width, self.config.target_height
        self._title_img = render_export_title_card(self._opening_name, self._eco, self._num_moves, width=pw, height=ph, bg_color=self.config.bg_color)
        self._end_img = render_export_end_screen(self._opening_name, self._eco, self._num_moves, width=pw, height=ph, bg_color=self.config.bg_color)
        self._display_previews()

    def _display_previews(self):
        if self._title_img:
            pm = QPixmap.fromImage(self._title_img.scaled(self.title_canvas.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.title_canvas.setPixmap(pm)
        if self._end_img:
            pm = QPixmap.fromImage(self._end_img.scaled(self.end_canvas.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.end_canvas.setPixmap(pm)

    def update_config(self, config): self.config = config; self._regenerate()

# ═══════════════════════════════════════════════════════════════════════════════
#  SETTINGS DIALOG
# ═══════════════════════════════════════════════════════════════════════════════
class SettingsDialog(QDialog):
    def __init__(self, export_config: ExportConfig, parent=None):
        super().__init__(parent)
        self.config = export_config; self.setWindowTitle("Settings"); self.setMinimumSize(520, 480)
        self.setStyleSheet("""
            QDialog { background: #1a1a2e; color: #ddd; }
            QTabWidget::pane { border: 1px solid #333; background: #1e1e2e; }
            QTabBar::tab { background: #16162a; color: #9a9abc; padding: 8px 16px; border: 1px solid #333; border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px; margin-right: 2px; }
            QTabBar::tab:selected { background: #1e1e2e; color: #fff; }
            QGroupBox { color: #aab; font-weight: bold; font-size: 12px; border: 1px solid #333; border-radius: 4px; margin-top: 10px; padding-top: 14px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QLabel { color: #ccc; font-size: 12px; }
            QSpinBox, QDoubleSpinBox, QComboBox, QLineEdit { background: #2a2a3a; color: #ddd; border: 1px solid #444; border-radius: 3px; padding: 3px 6px; font-size: 12px; }
            QCheckBox { color: #ccc; font-size: 12px; } QCheckBox::indicator { width: 16px; height: 16px; }
            QPushButton { background: #2a82da; color: #fff; border: none; border-radius: 4px; padding: 6px 16px; font-size: 12px; }
            QPushButton:hover { background: #3a92ea; } QPushButton#secondary { background: #3a3a4a; color: #ccc; }
            QPushButton#secondary:hover { background: #4a4a5a; }
            QSlider::groove:horizontal { height: 6px; background: #333; border-radius: 3px; }
            QSlider::handle:horizontal { width: 14px; height: 14px; background: #2a82da; border-radius: 7px; margin: -4px 0; }
        """)
        self._build_ui()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._build_video_tab(), "Video")
        tabs.addTab(self._build_title_tab(), "Title Card")
        tabs.addTab(self._build_end_tab(), "End Screen")
        tabs.addTab(self._build_appearance_tab(), "Appearance")
        tabs.addTab(self._build_advanced_tab(), "Advanced")
        main_layout.addWidget(tabs)
        btn_box = QHBoxLayout(); btn_box.addStretch()
        apply_btn = QPushButton("Apply"); apply_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel"); cancel_btn.setObjectName("secondary"); cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(cancel_btn); btn_box.addWidget(apply_btn); main_layout.addLayout(btn_box)

    def _build_video_tab(self):
        w = QWidget(); lay = QVBoxLayout(w)
        grp_preset = QGroupBox("Export Preset"); gl = QVBoxLayout(grp_preset)
        self.combo_preset = QComboBox(); self.combo_preset.addItems(EXPORT_PRESETS.keys()); self.combo_preset.setCurrentText(self.config.preset_name)
        self.combo_preset.currentTextChanged.connect(self._on_preset_changed)
        gl.addWidget(QLabel("Format:")); gl.addWidget(self.combo_preset)
        self.lbl_preset_info = QLabel(); self.lbl_preset_info.setStyleSheet("color:#8a8aaa;font-size:11px;")
        gl.addWidget(self.lbl_preset_info); self._update_preset_info()
        lay.addWidget(grp_preset)
        
        grp_timing = QGroupBox("Animation Timing"); tl = QGridLayout(grp_timing)
        tl.addWidget(QLabel("Move animation (s):"), 0, 0)
        self.spin_move_anim = QDoubleSpinBox(); self.spin_move_anim.setRange(0.1, 5.0); self.spin_move_anim.setSingleStep(0.1); self.spin_move_anim.setValue(self.config.move_anim_duration)
        tl.addWidget(self.spin_move_anim, 0, 1)
        tl.addWidget(QLabel("Pause after move (s):"), 1, 0)
        self.spin_pause = QDoubleSpinBox(); self.spin_pause.setRange(0.1, 5.0); self.spin_pause.setSingleStep(0.1); self.spin_pause.setValue(self.config.pause_after_move)
        tl.addWidget(self.spin_pause, 1, 1)
        tl.addWidget(QLabel("Study/Start Hold (s):"), 0, 2)
        self.spin_start_hold = QDoubleSpinBox(); self.spin_start_hold.setRange(1.0, 20.0); self.spin_start_hold.setSingleStep(0.5); self.spin_start_hold.setValue(self.config.start_hold_duration)
        tl.addWidget(self.spin_start_hold, 0, 3)
        tl.addWidget(QLabel("Study/End Hold (s):"), 1, 2)
        self.spin_end_hold = QDoubleSpinBox(); self.spin_end_hold.setRange(1.0, 20.0); self.spin_end_hold.setSingleStep(0.5); self.spin_end_hold.setValue(self.config.end_hold_duration)
        tl.addWidget(self.spin_end_hold, 1, 3)
        tl.addWidget(QLabel("FPS:"), 2, 0)
        self.spin_fps = QSpinBox(); self.spin_fps.setRange(10, 120); self.spin_fps.setValue(self.config.fps)
        tl.addWidget(self.spin_fps, 2, 1)
        lay.addWidget(grp_timing); lay.addStretch(); return w

    def _build_title_tab(self):
        w = QWidget(); lay = QVBoxLayout(w)
        grp = QGroupBox("Title Card"); gl = QGridLayout(grp)
        self.chk_title_enabled = QCheckBox("Enable title card"); self.chk_title_enabled.setChecked(self.config.title_enabled)
        gl.addWidget(self.chk_title_enabled, 0, 0, 1, 2)
        gl.addWidget(QLabel("Duration (s):"), 1, 0)
        self.spin_title_dur = QDoubleSpinBox(); self.spin_title_dur.setRange(1.0, 15.0); self.spin_title_dur.setSingleStep(0.5); self.spin_title_dur.setValue(self.config.title_duration)
        gl.addWidget(self.spin_title_dur, 1, 1)
        gl.addWidget(QLabel("Title override:"), 2, 0)
        self.edit_title_text = QLineEdit(); self.edit_title_text.setPlaceholderText("(use puzzle name if empty)"); self.edit_title_text.setText(self.config.title_text_override)
        gl.addWidget(self.edit_title_text, 2, 1)
        self.chk_watermark = QCheckBox("Show Shogi watermark"); self.chk_watermark.setChecked(self.config.show_logo_watermark)
        gl.addWidget(self.chk_watermark, 3, 0, 1, 2)
        lay.addWidget(grp); lay.addStretch(); return w

    def _build_end_tab(self):
        w = QWidget(); lay = QVBoxLayout(w)
        grp = QGroupBox("End Screen"); gl = QGridLayout(grp)
        self.chk_end_enabled = QCheckBox("Enable end screen"); self.chk_end_enabled.setChecked(self.config.end_title_enabled)
        gl.addWidget(self.chk_end_enabled, 0, 0, 1, 2)
        gl.addWidget(QLabel("Duration (s):"), 1, 0)
        self.spin_end_dur = QDoubleSpinBox(); self.spin_end_dur.setRange(1.0, 15.0); self.spin_end_dur.setSingleStep(0.5); self.spin_end_dur.setValue(self.config.end_title_duration)
        gl.addWidget(self.spin_end_dur, 1, 1)
        gl.addWidget(QLabel("Custom text:"), 2, 0)
        self.edit_end_text = QLineEdit(); self.edit_end_text.setPlaceholderText("(default: Puzzle Solved!)"); self.edit_end_text.setText(self.config.end_screen_text)
        gl.addWidget(self.edit_end_text, 2, 1)
        lay.addWidget(grp); lay.addStretch(); return w

    def _build_appearance_tab(self):
        w = QWidget(); lay = QVBoxLayout(w)
        grp_board = QGroupBox("Board Theme"); bl = QVBoxLayout(grp_board)
        self.combo_theme = QComboBox(); self.combo_theme.addItems(THEMES.keys()); self.combo_theme.setCurrentText(self.config.theme_name)
        bl.addWidget(QLabel("Theme:")); bl.addWidget(self.combo_theme)
        self.chk_flip = QCheckBox("Flip board (Gote at bottom)"); self.chk_flip.setChecked(self.config.flip_board)
        bl.addWidget(self.chk_flip)
        lay.addWidget(grp_board)
        arrow_label = QLabel("Arrow Style:")
        self.arrow_style_combo = QComboBox()
        for name in ARROW_STYLES_LIST: self.arrow_style_combo.addItem(name)
        current_arrow_name = next((k for k, v in ARROW_STYLES.items() if v == self.config.arrow_style), ARROW_STYLES_LIST[0])
        self.arrow_style_combo.setCurrentText(current_arrow_name)
        self.arrow_style_combo.currentTextChanged.connect(self._on_arrow_style_changed)
        arrow_row = QHBoxLayout(); arrow_row.addWidget(arrow_label); arrow_row.addWidget(self.arrow_style_combo, 1)
        lay.addLayout(arrow_row)
        
        grp_bg = QGroupBox("Background Color"); bgl = QHBoxLayout(grp_bg)
        self.slider_bg_r = QSlider(Qt.Horizontal); self.slider_bg_r.setRange(0, 255)
        self.slider_bg_g = QSlider(Qt.Horizontal); self.slider_bg_g.setRange(0, 255)
        self.slider_bg_b = QSlider(Qt.Horizontal); self.slider_bg_b.setRange(0, 255)
        r, g, b_ = self.config.bg_color
        self.slider_bg_r.setValue(r); self.slider_bg_g.setValue(g); self.slider_bg_b.setValue(b_)
        for s, lbl in [(self.slider_bg_r, "R"), (self.slider_bg_g, "G"), (self.slider_bg_b, "B")]:
            row = QHBoxLayout(); row.addWidget(QLabel(lbl)); row.addWidget(s); bgl.addLayout(row)
        self.bg_preview = QLabel(); self.bg_preview.setFixedSize(40, 40); bgl.addWidget(self.bg_preview)
        self._update_bg_preview()
        for s in (self.slider_bg_r, self.slider_bg_g, self.slider_bg_b): s.valueChanged.connect(self._update_bg_preview)
        lay.addWidget(grp_bg); lay.addStretch(); return w

    def _build_advanced_tab(self):
        w = QWidget(); lay = QVBoxLayout(w)
        dir_label = QLabel("Export Directory:")
        self.output_dir_edit = QLineEdit(self.config.output_dir); self.output_dir_edit.setReadOnly(True)
        browse_btn = QPushButton("Browse..."); browse_btn.clicked.connect(self._on_browse_output_dir)
        dir_layout = QHBoxLayout(); dir_layout.addWidget(dir_label); dir_layout.addWidget(self.output_dir_edit, 1); dir_layout.addWidget(browse_btn)
        lay.addLayout(dir_layout)
        grp_ff = QGroupBox("FFmpeg Encoding"); fl = QGridLayout(grp_ff)
        fl.addWidget(QLabel("CRF (quality):"), 0, 0)
        self.spin_crf = QSpinBox(); self.spin_crf.setRange(0, 51); self.spin_crf.setValue(self.config.ffmpeg_crf)
        fl.addWidget(self.spin_crf, 0, 1)
        fl.addWidget(QLabel("(lower = better quality, larger file)"), 0, 2)
        fl.addWidget(QLabel("Preset:"), 1, 0)
        self.combo_ff_preset = QComboBox(); self.combo_ff_preset.addItems(["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"])
        self.combo_ff_preset.setCurrentText(self.config.ffmpeg_preset)
        fl.addWidget(self.combo_ff_preset, 1, 1)
        lay.addWidget(grp_ff)
        info_grp = QGroupBox("System Info"); il = QVBoxLayout(info_grp)
        feats = []
        if HAS_FFMPEG: feats.append("FFmpeg")
        if HAS_IMAGEIO: feats.append("imageio")
        if HAS_PANDAS: feats.append("Pandas")
        il.addWidget(QLabel(f"Available: {', '.join(feats) if feats else 'None (basic mode)'}"))
        lay.addWidget(info_grp); lay.addStretch(); return w

    def _on_browse_output_dir(self):
        current_dir = self.output_dir_edit.text() or EXPORT_DIR
        new_dir = QFileDialog.getExistingDirectory(self, "Select Export Directory", current_dir)
        if new_dir: self.output_dir_edit.setText(new_dir); self.config.output_dir = new_dir

    def accept(self):
        self.config.output_dir = self.output_dir_edit.text()
        self.config.save()
        super().accept()

    def _on_arrow_style_changed(self, text):
        style = ARROW_STYLES.get(text, ARROW_STYLE_THICK)
        self.config.arrow_style = style

    def _on_preset_changed(self, name):
        self.config.apply_preset(name); self._update_preset_info()

    def _update_preset_info(self):
        p = self.config.preset
        self.lbl_preset_info.setText(f"{p.width}x{p.height}  ·  {p.description}  ·  {p.fps} FPS")

    def _update_bg_preview(self):
        r, g, b = self.slider_bg_r.value(), self.slider_bg_g.value(), self.slider_bg_b.value()
        self.bg_preview.setStyleSheet(f"QLabel{{background:rgb({r},{g},{b});border:1px solid #444;border-radius:4px;}}")

    def get_config(self):
        self.config.apply_preset(self.combo_preset.currentText())
        self.config.title_enabled = self.chk_title_enabled.isChecked()
        self.config.title_duration = self.spin_title_dur.value()
        self.config.start_hold_duration = self.spin_start_hold.value()
        self.config.end_hold_duration = self.spin_end_hold.value()
        self.config.title_text_override = self.edit_title_text.text()
        self.config.show_logo_watermark = self.chk_watermark.isChecked()
        self.config.end_title_duration = self.spin_end_dur.value()
        self.config.end_screen_text = self.edit_end_text.text()
        self.config.move_anim_duration = self.spin_move_anim.value()
        self.config.pause_after_move = self.spin_pause.value()
        self.config.fps = self.spin_fps.value()
        self.config.theme_name = self.combo_theme.currentText()
        self.config.flip_board = self.chk_flip.isChecked()
        self.config.bg_color = (self.slider_bg_r.value(), self.slider_bg_g.value(), self.slider_bg_b.value())
        self.config.ffmpeg_crf = self.spin_crf.value()
        self.config.ffmpeg_preset = self.combo_ff_preset.currentText()
        return self.config

# ═══════════════════════════════════════════════════════════════════════════════
#  BOARD WIDGET
# ═══════════════════════════════════════════════════════════════════════════════
class BoardWidget(QWidget):
    move_made = Signal(dict)
    move_animated = Signal(dict)
    move_attempted = Signal(int, int, int, int, object)

    def __init__(self, engine: ShogiEngine, theme_name="Classic", parent=None):
        super().__init__(parent)
        self.engine = engine; self.theme_name = theme_name; self.flipped = False
        self.selected = None; self.legal_targets = []
        self.anim_timer = None; self.anim_state = None
        self._arrow_style = ARROW_STYLE_THICK; self.puzzle_mode = False
        self.setMinimumSize(BOARD_PX, BOARD_PX)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)

    @property
    def theme(self): return THEMES.get(self.theme_name, THEMES["Classic"])
    def _sq_size(self): return min(self.width(), self.height()) // 9

    def _rc_from_pos(self, pos):
        sz = self._sq_size()
        col = pos.x() // sz; row = pos.y() // sz
        if self.flipped: col = 8 - col; row = 8 - row
        if 0 <= row < 9 and 0 <= col < 9: return row, col
        return None, None

    @property
    def arrow_style(self): return self._arrow_style
    @arrow_style.setter
    def arrow_style(self, value): self._arrow_style = value; self.update()

    def paintEvent(self, event):
        with paint_context(self) as p:
            sz = self._sq_size()
            check_sqs = self.engine.check_squares()
            img = render_board_image(
                self.engine.board, last_move=self.engine.last_move,
                selected=self.selected, legal_targets=self.legal_targets,
                check_squares=check_sqs, anim_state=self.anim_state,
                sq_size=sz, theme=self.theme, flipped=self.flipped, arrow_style=self.arrow_style)
            p.drawImage(0, 0, img.scaled(self.width(), self.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton: return
        r, c = self._rc_from_pos(event.pos())
        if r is None: return
        if self.selected:
            sr, sc = self.selected
            if (r, c) in self.legal_targets:
                self._execute_move(sr, sc, r, c)
                return
        piece = self.engine.board.piece_at(ShogiEngine.rc_to_sq(r, c))
        if piece:
            self.selected = (r, c)
            self.legal_targets = self.engine.legal_moves(r, c)
        else:
            self.selected = None; self.legal_targets = []
        self.update()

    def _execute_move(self, fr, fc, tr, tc, promo=None):
        if self.puzzle_mode:
            self.move_attempted.emit(fr, fc, tr, tc, promo)
            self.selected = None; self.legal_targets = []
            self.update()
            return
        result = self.engine.make_move(fr, fc, tr, tc, promo)
        if result:
            self.selected = None; self.legal_targets = []
            self._start_animation(result)
            self.move_made.emit(result)

    def play_external_move(self, usi_str):
        result = self.engine.make_move_usi(usi_str)
        if result:
            self._start_animation(result)
            self.move_made.emit(result)

    def _start_animation(self, result):
        if self.anim_timer: self.anim_timer.stop()
        self.anim_state = {
            'from': result['from'], 'to': result['to'],
            'piece_obj': result['piece_obj'], 'progress': 0.0}
        duration = ANIM_SPEED_DEFAULT
        steps = max(1, int(duration / 1000 * ANIM_FPS))
        self._anim_step = 0; self._anim_total = steps
        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self._tick_animation)
        interval = max(1, int(duration / steps))
        self.anim_timer.start(interval)

    def _tick_animation(self):
        if not self.anim_state: self.anim_timer.stop(); return
        self._anim_step += 1
        t = min(1.0, self._anim_step / self._anim_total)
        self.anim_state['progress'] = _ease_out_cubic(t)
        self.update()
        if t >= 1.0:
            self.anim_timer.stop()
            result_copy = dict(self.anim_state)
            self.anim_state = None
            self.update()
            self.move_animated.emit(result_copy)

    def reset_view(self):
        self.selected = None; self.legal_targets = []
        self.update()

# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN WINDOW
# ═══════════════════════════════════════════════════════════════════════════════
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Shogi Puzzle Trainer")
        self.setMinimumSize(1280, 800); self.resize(1440, 900)
        self.engine = ShogiEngine()
        self.config = ExportConfig()
        self.dp = DataProvider()
        self.puzzle_session = PuzzleSession(self.engine)
        self.pending_opp_move = None
        self._apply_global_style()
        self._build_ui()
        self._connect_signals()

    def _apply_global_style(self):
        self.setStyleSheet("""
            QMainWindow { background: #12121e; }
            QWidget { background: #12121e; color: #ddd; font-family: 'Segoe UI', sans-serif; }
            QSplitter::handle { background: #2a2a3a; width: 3px; }
            QSplitter::handle:hover { background: #2a82da; }
            QStatusBar { background: #0e0e1a; color: #6a6a8a; font-size: 11px; border-top: 1px solid #222; }
            QMenuBar { background: #16162a; color: #ccc; border-bottom: 1px solid #222; }
            QMenuBar::item:selected { background: #2a82da; }
            QMenu { background: #1e1e2e; color: #ddd; border: 1px solid #333; }
            QMenu::item:selected { background: #2a82da; }
            QToolBar { background: #16162a; border-bottom: 1px solid #222; spacing: 4px; padding: 2px; }
            QToolButton { background: transparent; color: #ccc; border: 1px solid transparent; border-radius: 4px; padding: 4px 8px; font-size: 12px; }
            QToolButton:hover { background: #2a2a3a; border-color: #444; }
            QToolButton:pressed { background: #2a82da; }
        """)

    def _build_ui(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")
        clear_action = QAction("Clear Database", self); clear_action.triggered.connect(self._clear_db)
        file_menu.addAction(clear_action)
        file_menu.addSeparator()
        exit_action = QAction("Exit", self); exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        toolbar = self.addToolBar("Main"); toolbar.setMovable(False)
        self.btn_settings = QToolButton(); self.btn_settings.setText("⚙ Settings"); self.btn_settings.clicked.connect(self._show_settings)
        toolbar.addWidget(self.btn_settings); toolbar.addSeparator()
        self.btn_reset = QToolButton(); self.btn_reset.setText("⟳ Reset"); self.btn_reset.clicked.connect(self._reset_board)
        toolbar.addWidget(self.btn_reset); toolbar.addSeparator()
        self.btn_flip = QToolButton(); self.btn_flip.setText("⇅ Flip"); self.btn_flip.clicked.connect(self._flip_board)
        toolbar.addWidget(self.btn_flip); toolbar.addSeparator()
        self.btn_batch_export = QToolButton(); self.btn_batch_export.setText("▶ Batch Export")
        self.btn_batch_export.setStyleSheet("QToolButton{background:#2a82da;color:#fff;border-radius:4px;padding:4px 12px}QToolButton:hover{background:#3a92ea}")
        self.btn_batch_export.clicked.connect(self._batch_export)
        toolbar.addWidget(self.btn_batch_export)
        
        central = QWidget(); self.setCentralWidget(central)
        main_layout = QHBoxLayout(central); main_layout.setContentsMargins(6, 6, 6, 6)
        splitter = QSplitter(Qt.Horizontal)
        
        left_panel = QWidget(); left_layout = QVBoxLayout(left_panel); left_layout.setContentsMargins(0, 0, 0, 0)
        self.puzzles_list = PaginatedPuzzlesWidget(self.dp)
        left_layout.addWidget(self.puzzles_list)
        left_panel.setMinimumWidth(320); left_panel.setMaximumWidth(500)
        splitter.addWidget(left_panel)
        
        center_panel = QWidget(); center_layout = QVBoxLayout(center_panel); center_layout.setContentsMargins(0, 0, 0, 0)
        self.board_widget = BoardWidget(self.engine, self.config.theme_name)
        center_layout.addWidget(self.board_widget, 1)
        self.notation_display = QTextEdit(); self.notation_display.setReadOnly(True); self.notation_display.setMaximumHeight(80)
        self.notation_display.setStyleSheet("QTextEdit{background:#1e1e2a;color:#ccc;border:1px solid #333;border-radius:4px;font-family:monospace;font-size:12px;padding:4px;}")
        center_layout.addWidget(self.notation_display)
        splitter.addWidget(center_panel)
        
        right_panel = QWidget(); right_layout = QVBoxLayout(right_panel); right_layout.setContentsMargins(4, 4, 4, 4)
        info_grp = QGroupBox("Current Puzzle")
        info_grp.setStyleSheet("QGroupBox{color:#aab;font-weight:bold;border:1px solid #333;border-radius:4px;margin-top:10px;padding-top:14px;}QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 4px;}")
        info_lay = QVBoxLayout(info_grp)
        self.lbl_puzzle_id = QLabel("No puzzle selected"); self.lbl_puzzle_id.setWordWrap(True); self.lbl_puzzle_id.setStyleSheet("font-size:14px;font-weight:bold;color:#eee;")
        info_lay.addWidget(self.lbl_puzzle_id)
        self.lbl_rating = QLabel("Rating: —"); self.lbl_rating.setStyleSheet("color:#8a8aaa;font-size:12px;")
        info_lay.addWidget(self.lbl_rating)
        self.lbl_themes = QLabel("Themes: —"); self.lbl_themes.setWordWrap(True); self.lbl_themes.setStyleSheet("color:#8a8aaa;font-size:12px;")
        info_lay.addWidget(self.lbl_themes)
        self.lbl_opening = QLabel("Opening: —"); self.lbl_opening.setWordWrap(True); self.lbl_opening.setStyleSheet("color:#8a8aaa;font-size:12px;")
        info_lay.addWidget(self.lbl_opening)
        self.lbl_game_url = QLabel("Game URL: —"); self.lbl_game_url.setOpenExternalLinks(True); self.lbl_game_url.setWordWrap(True); self.lbl_game_url.setStyleSheet("color:#2a82da;font-size:12px;")
        info_lay.addWidget(self.lbl_game_url)
        right_layout.addWidget(info_grp)
        
        self.preview_widget = PreviewWidget(self.config)
        right_layout.addWidget(self.preview_widget)
        right_layout.addStretch()
        right_panel.setMinimumWidth(260); right_panel.setMaximumWidth(320)
        splitter.addWidget(right_panel)
        
        splitter.setStretchFactor(0, 0); splitter.setStretchFactor(1, 1); splitter.setStretchFactor(2, 0)
        main_layout.addWidget(splitter)
        log(f"Ready — {self.dp.total_puzzles} puzzles loaded", "INFO")

    def _connect_signals(self):
        self.puzzles_list.puzzle_selected.connect(self._on_puzzle_selected)
        self.board_widget.move_attempted.connect(self._on_move_attempted)
        self.board_widget.move_animated.connect(self._on_move_animated)

    def _clear_puzzle_ui(self):
        self.lbl_puzzle_id.setText("No puzzle selected"); self.lbl_rating.setText("Rating: —")
        self.lbl_themes.setText("Themes: —"); self.lbl_opening.setText("Opening: —")
        self.lbl_game_url.setText("Game URL: —")
        self.preview_widget.set_opening("No puzzle", "", 0)
        self.board_widget.puzzle_mode = False; self.board_widget.reset_view()
        self.pending_opp_move = None

    def _on_puzzle_selected(self, puzzle_id):
        rec = self.dp.get_puzzle(puzzle_id)
        if not rec:
            self._clear_puzzle_ui()
            self.statusBar().showMessage(f"Puzzle {puzzle_id} not found.")
            log(f"Puzzle {puzzle_id} not found in database.", "ERROR")
            return
            
        self.puzzle_session.load_puzzle(rec)
        self.board_widget.puzzle_mode = True; self.board_widget.reset_view(); self.board_widget.update()
        self.lbl_puzzle_id.setText(f"Puzzle: {rec['id']}")
        self.lbl_rating.setText(f"Rating: {rec['rating']}")
        self.lbl_themes.setText(f"Themes: {rec['themes']}")
        self.lbl_opening.setText(f"Opening: {rec['opening_tags']}")
        self.lbl_game_url.setText(f"Game URL: <a href='{rec['game_url']}'>{rec['game_url']}</a>")
        
        themes = rec.get('themes', '').replace(',', ' & ').strip().title()
        rating = rec.get('rating', 'Unknown')
        puzzle_name = f"[{rating}] {themes} Puzzle" if themes else f"[{rating}] Puzzle #{rec['id']}"
        usi_moves = rec['moves'].split()
        self.preview_widget.set_opening(puzzle_name, themes if themes else rec.get('opening_tags', 'Unknown'), len(usi_moves))
        self.statusBar().showMessage(f"Loaded {puzzle_name}")
        log(f"Loaded puzzle {rec['id']} with rating {rec['rating']} and themes {rec['themes']}", "INFO")

    def _on_move_attempted(self, fr, fc, tr, tc, promo):
        from_sq = ShogiEngine.rc_to_sq(fr, fc)
        to_sq = ShogiEngine.rc_to_sq(tr, tc)
        move = shogi.Move(from_sq, to_sq, promotion=promo if promo else False)
        usi = move.usi()
        status, user_usi, opp_usi = self.puzzle_session.try_move_usi(usi)
        
        if status == "correct":
            self.pending_opp_move = opp_usi
            self.board_widget.play_external_move(user_usi)
        elif status == "incorrect":
            self.statusBar().showMessage("Incorrect move! Try again.")
            log(f"Incorrect move attempted: {usi}", "WARN")
        elif status == "solved":
            self.board_widget.play_external_move(user_usi)
            self.statusBar().showMessage("Puzzle solved!")
            log(f"Puzzle {self.puzzle_session.current_puzzle.id} solved by user.", "INFO")

    def _on_move_animated(self, anim_result):
        if self.pending_opp_move:
            opp_usi = self.pending_opp_move
            self.pending_opp_move = None
            QTimer.singleShot(300, lambda: self.board_widget.play_external_move(opp_usi))

    def _reset_board(self):
        if self.puzzle_session.current_puzzle:
            self.puzzle_session.load_puzzle(self.puzzle_session.current_puzzle)
            self.board_widget.reset_view(); self.pending_opp_move = None

    def _flip_board(self):
        self.board_widget.flipped = not self.board_widget.flipped
        self.config.flip_board = self.board_widget.flipped
        self.config.save(); self.board_widget.update()

    def _show_settings(self):
        dlg = SettingsDialog(self.config, self)
        if dlg.exec() == QDialog.Accepted:
            self.config = dlg.get_config(); self.config.save()
            self.board_widget.theme_name = self.config.theme_name
            self.board_widget.flipped = self.config.flip_board
            self.board_widget.update(); self.preview_widget.update_config(self.config)
            self.statusBar().showMessage("Settings updated and auto-saved")
            log("User updated and auto-saved settings.", "INFO")

    def _batch_export(self):
        ids = self.puzzles_list.get_selected_ids()
        if not ids:
            self.statusBar().showMessage("No puzzles selected for export — use checkboxes")
            log("Batch export aborted: No puzzles selected", "WARN")
            return
            
        raw_records = [self.dp.get_puzzle(pid) for pid in ids]
        raw_records = [r for r in raw_records if r]
        puzzles_data = []
        for rec in raw_records:
            usi_moves = rec.get('moves', '').split()
            rec['moves'] = usi_moves
            themes = rec.get('themes', '').replace(',', ' & ').strip().title()
            rating = rec.get('rating', 'Unknown')
            rec['name'] = f"[{rating}] {themes} Puzzle" if themes else f"[{rating}] Puzzle #{rec['id']}"
            rec['eco'] = themes if themes else rec.get('opening_tags', 'Unknown')
            
            notations = []
            try:
                temp_board = shogi.Board(rec.get('sfen', ''))
                for usi in usi_moves:
                    try:
                        m = shogi.Move.from_usi(usi)
                        notations.append(temp_board.san(m))
                        temp_board.push(m)
                    except Exception: break
            except Exception as e: log(f"Invalid SFEN for puzzle {rec.get('id')}: {e}", "WARN")
            rec['notations'] = notations
            puzzles_data.append(rec)
            
        if not puzzles_data:
            self.statusBar().showMessage("No valid puzzles found for export.")
            log("Batch export aborted: No valid puzzles after processing.", "WARN")
            return
            
        # Note: BatchExportDialog and VideoExportWorker are preserved from original structure 
        # but adapted to use 'sfen', 'usi_moves', and shogi.Board logic internally.
        # For brevity in this response, the dialog instantiation remains the same, 
        # relying on the adapted helper methods in the Worker class below.
        dlg = BatchExportDialog(puzzles_data, self.config, self)
        dlg.exec()

    def _clear_db(self):
        self.dp.clear_all(); self.puzzles_list._current_page = 0
        self.puzzles_list._refresh(); self.statusBar().showMessage("Database cleared")
        log("Database cleared by user action.", "INFO")

    def closeEvent(self, event):
        self.config.save(); self.dp.close(); event.accept()

# ═══════════════════════════════════════════════════════════════════════════════
#  BATCH EXPORT DIALOG & WORKER (Adapted for Shogi)
# ═══════════════════════════════════════════════════════════════════════════════
class BatchExportDialog(QDialog):
    def __init__(self, puzzles_list, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Batch Export"); self.setMinimumSize(520, 420)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setModal(True)
        self.puzzles_list = puzzles_list; self.config = config
        self.worker = None; self._completed = 0; self._failed = 0
        self._results = []; self._total = len(puzzles_list)
        self._build_ui(); self._start_export()

    def _build_ui(self):
        layout = QVBoxLayout(self); layout.setSpacing(10)
        self.lbl_overall = QLabel(f"Exporting {self._total} puzzle(s)…")
        layout.addWidget(self.lbl_overall)
        self.progress_overall = QProgressBar(); self.progress_overall.setRange(0, self._total); self.progress_overall.setValue(0)
        self.progress_overall.setFormat("%v / %m videos")
        layout.addWidget(self.progress_overall)
        self.lbl_current = QLabel("Preparing…"); layout.addWidget(self.lbl_current)
        self.progress_current = QProgressBar(); self.progress_current.setRange(0, 100); self.progress_current.setValue(0); self.progress_current.setFormat("%p%")
        layout.addWidget(self.progress_current)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Puzzle", "Status", "File"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.table)
        btn_layout = QHBoxLayout()
        self.btn_cancel = QPushButton("Cancel"); self.btn_cancel.clicked.connect(self._on_cancel)
        self.btn_open_folder = QPushButton("Open Folder"); self.btn_open_folder.clicked.connect(self._open_output_folder); self.btn_open_folder.setEnabled(False)
        self.btn_close = QPushButton("Close"); self.btn_close.clicked.connect(self.accept); self.btn_close.setEnabled(False)
        btn_layout.addStretch(); btn_layout.addWidget(self.btn_open_folder); btn_layout.addWidget(self.btn_cancel); btn_layout.addWidget(self.btn_close)
        layout.addLayout(btn_layout)

    def _start_export(self):
        self.worker = VideoExportWorker(self.puzzles_list, self.config, parent=self)
        self.worker.video_done.connect(self._on_video_done, Qt.QueuedConnection)
        self.worker.progress.connect(self._on_frame_progress, Qt.QueuedConnection)
        self.worker.finished.connect(self._on_batch_finished, Qt.QueuedConnection)
        self.worker.error.connect(self._on_error, Qt.QueuedConnection)
        self.worker.start()

    def _on_frame_progress(self, current_frame, total_frames):
        if total_frames > 0: self.progress_current.setValue(min(100, int(100 * current_frame / total_frames)))

    def _on_video_done(self, video_index, output_path):
        self._completed += 1
        name = self.puzzles_list[video_index].get("name", f"Video {video_index}")
        self._results.append((name, "✓ Done", output_path))
        self._add_table_row(name, "✓ Done", output_path)
        self.progress_overall.setValue(self._completed + self._failed)
        self.lbl_overall.setText(f"Exported {self._completed} of {self._total}" + (f"  ({self._failed} failed)" if self._failed else ""))
        self.lbl_current.setText(f"✓ {name}"); self.progress_current.setValue(100)

    def _on_error(self, vid_idx, error_msg):
        self._failed += 1
        name = self.puzzles_list[vid_idx].get("name", f"Video {vid_idx}") if vid_idx < len(self.puzzles_list) else "Unknown"
        self._results.append((name, "✗ Failed", error_msg))
        self._add_table_row(name, "✗ Failed", error_msg[:120])
        self.progress_overall.setValue(self._completed + self._failed)
        self.lbl_overall.setText(f"Exported {self._completed} of {self._total}  ({self._failed} failed)")
        self.lbl_current.setText(f"✗ Failed: {name}")
        log(f"Error exporting video {vid_idx} ({name}): {error_msg}", "ERROR")
        if self._completed + self._failed >= self._total: self._on_batch_finished("batch_complete")

    def _on_batch_finished(self, result):
        self.lbl_overall.setText(f"Batch complete: {self._completed} succeeded, {self._failed} failed")
        self.lbl_current.setText("All exports finished."); self.progress_current.setValue(100); self.progress_overall.setValue(self._total)
        self.btn_cancel.setEnabled(False); self.btn_close.setEnabled(True); self.btn_open_folder.setEnabled(True)
        if self._failed == 0:
            self.lbl_current.setStyleSheet("color: #4CAF50; font-weight: bold;")
            self.lbl_current.setText(f"✓ All {self._completed} videos exported successfully!")
        else:
            self.lbl_current.setStyleSheet("color: #FF9800; font-weight: bold;")
            self.lbl_current.setText(f"⚠ {self._completed} succeeded, {self._failed} failed. Check the table.")

    def _on_cancel(self):
        if self.worker and self.worker.isRunning():
            self.btn_cancel.setEnabled(False); self.btn_cancel.setText("Cancelling…"); self.lbl_current.setText("Cancelling…")
            self.worker.cancel(); QTimer.singleShot(5000, self._force_cleanup)
        else: self.reject()

    def _force_cleanup(self):
        if self.worker and self.worker.isRunning(): self.worker.terminate(); self.worker.wait(2000)
        self._on_batch_finished("cancelled")

    def _add_table_row(self, name, status, detail):
        row = self.table.rowCount(); self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(name))
        si = QTableWidgetItem(status); si.setForeground(QColor("#4CAF50") if "✓" in status else QColor("#F44336"))
        self.table.setItem(row, 1, si)
        di = QTableWidgetItem(detail); di.setToolTip(detail)
        self.table.setItem(row, 2, di); self.table.scrollToBottom()

    def _open_output_folder(self):
        path = self.config.output_dir
        if not os.path.isdir(path): os.makedirs(path, exist_ok=True)
        if sys.platform == "win32": os.startfile(path)
        elif sys.platform == "darwin": subprocess.Popen(["open", path])
        else: subprocess.Popen(["xdg-open", path])

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning(): self._on_cancel(); event.ignore()
        else: event.accept()

    def cleanup(self):
        if self.worker: self.worker.cancel(); self.worker.wait(3000)


class VideoExportWorker(QThread):
    progress = Signal(int, int)
    finished = Signal(str)
    error = Signal(int, str)
    video_done = Signal(int, str)
    _FLUSH_THRESHOLD = 32 * 1024 * 1024

    def __init__(self, puzzles_list, config, parent=None):
        super().__init__(parent)
        self.puzzles_list = puzzles_list; self.config = config; self._cancel = False
        self.tmpdir = os.path.join(os.getcwd(), "shogi_export_tmp")
        os.makedirs(self.tmpdir, exist_ok=True)

    def cancel(self): self._cancel = True

    def run(self):
        total = len(self.puzzles_list)
        for vid_idx, puzzle_data in enumerate(self.puzzles_list):
            if self._cancel: self.error.emit(vid_idx, "Export cancelled"); return
            try:
                path = self._export_single(puzzle_data, vid_idx)
                if path: self.video_done.emit(vid_idx, path)
                elif self._cancel: return
            except Exception as exc:
                self.error.emit(vid_idx, f"Error on '{puzzle_data.get('name', '?')}': {exc}")
        self.finished.emit("batch_complete")

    def _export_single(self, puzzle_data, vid_idx):
        cfg = self.config; preset = cfg.preset; w, h = preset.width, preset.height; fps = cfg.fps
        theme = THEMES.get(cfg.theme_name, THEMES["Classic"])
        bg_color = cfg.bg_color; arrow_sty = cfg.arrow_style; flipped = cfg.flip_board
        is_board_only = preset.is_board_only
        layout = CompositeLayout(w, h, sq_size=None, is_vertical=preset.is_vertical, is_square=preset.is_square, is_board_only=is_board_only, show_title=False)
        optimal_sq_size = layout.sq_size
        
        os.makedirs(cfg.output_dir, exist_ok=True)
        safe = sanitize_filename(puzzle_data["name"]); ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = os.path.join(cfg.output_dir, f"{safe}_{ts}.mp4")
        
        usi_moves = puzzle_data.get("moves", []); notations = puzzle_data.get("notations", [])
        if not notations: notations = self._generate_notations(usi_moves)
        sfen = puzzle_data.get("sfen")
        
        board_states = self._precompute_boards(usi_moves, sfen=sfen)
        move_metas = self._precompute_move_meta(board_states, usi_moves)
        
        n_anim = max(1, int(cfg.move_anim_duration * fps))
        ease_vals = [_ease_out_cubic(i / max(1, n_anim - 1)) for i in range(n_anim)]
        n_hold = max(1, int(cfg.pause_after_move * fps))
        plan = self._build_frame_plan(cfg, fps, usi_moves, move_metas, n_anim, n_hold)
        
        sr = 44100; total_frames = sum(p[1] for p in plan)
        if total_frames == 0: self.error.emit(vid_idx, f"No frames for '{puzzle_data['name']}'"); return None
        if not HAS_FFMPEG: self.error.emit(vid_idx, "ffmpeg not found on PATH"); return None
        
        temp_audio_path = os.path.join(self.tmpdir, f"shogi_export_audio_{vid_idx}_{int(time.time())}.wav")
        try:
            total_duration = total_frames / fps; total_samples = int(total_duration * sr) + sr
            audio_buffer = np.zeros(total_samples, dtype=np.float64)
            t = 0.0
            if cfg.title_enabled: t += cfg.title_duration
            audio_events = []
            if cfg.start_hold_duration > 0:
                if cfg.start_hold_duration >= 1.0: audio_events.append((t + cfg.start_hold_duration - 1.0, 'tick'))
                for sec in range(1, int(cfg.start_hold_duration)):
                    tick_time = t + float(sec)
                    if not any(abs(ev[0] - tick_time) < 0.01 for ev in audio_events): audio_events.append((tick_time, 'tick'))
                audio_events.append((t + cfg.start_hold_duration, 'start'))
                t += cfg.start_hold_duration
            else:
                audio_events.append((t, 'start'))
            t += cfg.pause_after_move
            
            for mi in range(len(usi_moves)):
                meta = move_metas[mi]; snd = 'move'
                if meta.get('checkmate'): snd = 'checkmate'
                elif meta.get('check'): snd = 'check'
                elif meta.get('promo'): snd = 'promote'
                elif meta.get('captured') != '.': snd = 'capture'
                audio_events.append((t, snd))
                t += cfg.move_anim_duration
                t += cfg.pause_after_move
                
            if cfg.end_title_enabled: audio_events.append((t, 'end'))
            
            for t_sec, snd_name in audio_events:
                samples = self._get_sound_samples(snd_name, sr)
                start_idx = int(t_sec * sr); end_idx = start_idx + len(samples)
                if end_idx > len(audio_buffer):
                    new_buf = np.zeros(end_idx + sr, dtype=np.float64); new_buf[:len(audio_buffer)] = audio_buffer
                    audio_buffer = new_buf
                audio_buffer[start_idx:end_idx] += samples
                
            audio_i16 = _to_i16(audio_buffer)
            with wave.open(temp_audio_path, 'w') as wv:
                wv.setnchannels(1); wv.setsampwidth(2); wv.setframerate(sr); wv.writeframes(audio_i16.tobytes())
                
            cmd = self._ffmpeg_cmd(w, h, fps, cfg, puzzle_data, out, temp_audio_path)
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            stderr_chunks: list[bytes] = []; stderr_exc: list[Exception] = []
            def _drain_stderr():
                try:
                    while True:
                        chunk = proc.stderr.read(8192)
                        if not chunk: break
                        stderr_chunks.append(chunk)
                except Exception as e: stderr_exc.append(e)
            stderr_thread = threading.Thread(target=_drain_stderr, daemon=True); stderr_thread.start()
            
            name = puzzle_data["name"]; eco = puzzle_data.get("eco", ""); n_mv = len(usi_moves)
            title_bgr = None
            if cfg.title_enabled:
                img = render_export_title_card(name, eco, n_mv, width=w, height=h, bg_color=bg_color)
                title_bgr = _qimage_to_bgr_bytes(img)
            end_bgr = None
            if cfg.end_title_enabled:
                img = render_export_end_screen(name, eco, n_mv, width=w, height=h, bg_color=bg_color)
                end_bgr = _qimage_to_bgr_bytes(img)
                
            start_img = render_composite_frame(board_states[0], notations, 0, width=w, height=h, sq_size=optimal_sq_size, theme=theme, flipped=flipped, bg_color=bg_color, arrow_style=arrow_sty, is_board_only=is_board_only)
            start_bgr = _qimage_to_bgr_bytes(start_img)
            
            hold_cache: dict[int, bytes] = {}; static_board_cache: dict[int, QImage] = {}
            buf = bytearray(); rendered = 0; last_pct = -1
            def _flush():
                nonlocal buf
                if buf:
                    try: proc.stdin.write(buf)
                    except BrokenPipeError: raise RuntimeError("ffmpeg pipe broken")
                    buf = bytearray()
            def _queue(bgr: bytes):
                nonlocal rendered, last_pct
                buf.extend(bgr); rendered += 1
                if len(buf) >= self._FLUSH_THRESHOLD: _flush()
                pct = rendered * 50 // total_frames
                if pct != last_pct: self.progress.emit(rendered, total_frames); last_pct = pct
                
            try:
                for item in plan:
                    if self._cancel: _flush(); self._safe_close(proc); stderr_thread.join(timeout=2); return None
                    kind = item[0]; count = item[1]
                    if kind == 'title':
                        for _ in range(count): _queue(title_bgr)
                    elif kind == 'start_hold':
                        for _ in range(count): _queue(start_bgr)
                    elif kind == 'end':
                        for _ in range(count): _queue(end_bgr)
                    elif kind == 'anim':
                        _, _, mi, anim_base = item; b = board_states[mi]
                        if mi >= len(board_states): continue
                        if mi not in static_board_cache:
                            static_board_cache[mi] = render_board_image(
                                b, last_move=move_metas[mi]['last_move'],
                                check_squares=self._check_sqs(b),
                                anim_state=anim_base, sq_size=optimal_sq_size, theme=theme,
                                flipped=flipped, arrow_style=arrow_sty, static_only=True
                            )
                        static_img = static_board_cache[mi]
                        for af in range(count):
                            state = dict(anim_base); state['progress'] = ease_vals[af]
                            img = render_composite_frame(b, notations, mi, anim_state=state,
                                width=w, height=h, sq_size=optimal_sq_size, theme=theme, flipped=flipped,
                                bg_color=bg_color, arrow_style=arrow_sty, is_board_only=is_board_only,
                                static_board_img=static_img)
                            _queue(_qimage_to_bgr_bytes(img))
                    elif kind in ('hold', 'last_hold'):
                        _, _, bidx, last_mv = item
                        if bidx >= len(board_states): continue
                        if bidx not in hold_cache:
                            b = board_states[bidx]; chk = self._check_sqs(b)
                            img = render_composite_frame(b, notations, bidx - 1, last_move=last_mv, check_squares=chk, width=w, height=h, sq_size=optimal_sq_size, theme=theme, flipped=flipped, bg_color=bg_color, arrow_style=arrow_sty, is_board_only=is_board_only)
                            hold_cache[bidx] = _qimage_to_bgr_bytes(img)
                        for _ in range(count): _queue(hold_cache[bidx])
                _flush()
            except RuntimeError: pass
            
            try: proc.stdin.close()
            except BrokenPipeError: pass
            rc = proc.wait(); stderr_thread.join(timeout=5)
            stderr_text = b"".join(stderr_chunks).decode("utf-8", errors="replace")
            if rc != 0: self.error.emit(vid_idx, f"ffmpeg exited code {rc}: {stderr_text[-800:]}"); return None
            if not os.path.exists(out): self.error.emit(vid_idx, f"Output file not found: {out}"); return None
            if os.path.getsize(out) < 1000: self.error.emit(vid_idx, f"Output file is suspiciously small: {out}"); return None
            return out
        finally:
            try:
                if os.path.exists(temp_audio_path): os.remove(temp_audio_path)
            except Exception: pass

    @staticmethod
    def _generate_notations(usi_moves):
        board = shogi.Board(); notations = []
        for usi in usi_moves:
            try:
                move = shogi.Move.from_usi(usi)
                notations.append(board.san(move))
                board.push(move)
            except Exception: break
        return notations

    @staticmethod
    def _precompute_boards(usi_moves, sfen=None):
        if sfen: states = [shogi.Board(sfen)]
        else: states = [shogi.Board()]
        for usi in usi_moves:
            b = states[-1]
            try: b.push(shogi.Move.from_usi(usi))
            except Exception: break
            states.append(b)
        return states

    @staticmethod
    def _precompute_move_meta(board_states, usi_moves):
        metas = []
        for mi, usi in enumerate(usi_moves):
            move = shogi.Move.from_usi(usi); b_before = board_states[mi]
            b_after = board_states[mi + 1] if mi + 1 < len(board_states) else None
            bfr = 8 - (move.from_square // 9) if move.from_square is not None else None
            bfc = move.from_square % 9 if move.from_square is not None else None
            btr = 8 - (move.to_square // 9); btc = move.to_square % 9
            
            piece_obj = b_before.piece_at(move.from_square) if move.from_square is not None else None
            cap = b_before.piece_at(move.to_square)
            cap_sym = cap.symbol() if cap else '.'
            is_promo = move.promotion
            is_check = b_after.is_check() if b_after else False
            is_mate = b_after.is_checkmate() if b_after else False
            
            metas.append({
                'from': (bfr, bfc) if move.from_square is not None else None, 
                'to': (btr, btc), 'piece_obj': piece_obj, 'captured': cap_sym,
                'last_move': ((bfr, bfc), (btr, btc)) if move.from_square is not None else (None, (btr, btc)), 
                'promo': is_promo, 'check': is_check, 'checkmate': is_mate,
            })
        return metas

    @staticmethod
    def _get_sound_samples(sound_name, sr=44100):
        # Simplified sound generation (same as original, adapted for Shogi context)
        def make_wood_hit(freq, duration, volume, noise_vol=0.3, decay_factor=25.0):
            n = int(sr * duration)
            if n <= 0: return np.zeros(1, dtype=np.float64)
            t = np.arange(n, dtype=np.float64) / sr
            rng = np.random.RandomState(42)
            noise = rng.randn(n)
            pitch = np.sin(2.0 * np.pi * freq * t) + 0.5 * np.sin(2.0 * np.pi * freq * 2.01 * t)
            out = pitch + (noise_vol * noise)
            env = np.exp(-decay_factor * t)
            attack_n = int(sr * 0.003)
            if attack_n > 1: env[:attack_n] *= np.linspace(0.0, 1.0, attack_n)
            return volume * out * env
            
        def make_tone(freq, duration, volume, harmonics=2, decay_factor=8.0, vibrato=0.0):
            n = int(sr * duration)
            if n <= 0: return np.zeros(1, dtype=np.float64)
            t = np.arange(n, dtype=np.float64) / sr
            mod = 1.0 + vibrato * np.sin(2.0 * np.pi * 5.0 * t)
            phase = 2.0 * np.pi * freq * t * mod
            out = np.sin(phase)
            for h in range(2, harmonics + 1): out += (1.0 / (h**1.5)) * np.sin(phase * h)
            env = np.exp(-decay_factor * t)
            attack_n = int(sr * 0.005)
            if attack_n > 1: env[:attack_n] *= np.linspace(0.0, 1.0, attack_n)
            return volume * out * env
            
        def make_chord(freqs, duration, volume, decay_factor=3.0):
            n = int(sr * duration)
            if n <= 0: return np.zeros(1, dtype=np.float64)
            t = np.arange(n, dtype=np.float64) / sr
            out = np.zeros(n, dtype=np.float64)
            for f in freqs:
                out += np.sin(2.0 * np.pi * f * t) + 0.5 * np.sin(2.0 * np.pi * (f * 1.002) * t)
            out /= len(freqs)
            env = np.exp(-decay_factor * t)
            attack_n = int(sr * 0.01)
            if attack_n > 1: env[:attack_n] *= np.linspace(0.0, 1.0, attack_n)
            return volume * out * env

        if sound_name == 'move': return make_wood_hit(800, 0.06, 0.45, noise_vol=0.4, decay_factor=35.0)
        elif sound_name == 'capture': return make_wood_hit(350, 0.10, 0.6, noise_vol=0.6, decay_factor=20.0)
        elif sound_name == 'check': return make_tone(880, 0.25, 0.4, harmonics=3, decay_factor=5.0, vibrato=0.02)
        elif sound_name == 'checkmate': return make_chord([523.25, 659.25, 783.99, 1046.50], 0.8, 0.5, decay_factor=2.0)
        elif sound_name == 'promote': return np.concatenate([make_tone(523.25, 0.08, 0.45), make_tone(659.25, 0.08, 0.45), make_tone(783.99, 0.08, 0.45), make_tone(1046.50, 0.20, 0.55)])
        elif sound_name == 'start': return np.concatenate([make_tone(261.63, 0.12, 0.5), np.zeros(max(1, int(sr * 0.04)), dtype=np.float64), make_tone(392.00, 0.20, 0.5)])
        elif sound_name == 'tick': return make_wood_hit(2500, 0.02, 0.25, noise_vol=0.7, decay_factor=50.0)
        elif sound_name == 'end': return np.concatenate([make_tone(392.00, 0.15, 0.5), np.zeros(max(1, int(sr * 0.05)), dtype=np.float64), make_tone(261.63, 0.30, 0.5)])
        return np.zeros(int(sr * 0.1), dtype=np.float64)

    @staticmethod
    def _check_sqs(board):
        if board.is_check():
            k = board.king(board.turn)
            if k is not None: return [(8 - (k // 9), k % 9)]
        return []

    @staticmethod
    def _build_frame_plan(cfg, fps, usi_moves, move_metas, n_anim, n_hold):
        plan = []
        if cfg.title_enabled: plan.append(('title', max(1, int(cfg.title_duration * fps))))
        start_hold_frames = max(1, int(cfg.start_hold_duration * fps))
        plan.append(('start_hold', start_hold_frames))
        num_valid_moves = min(len(usi_moves), len(move_metas))
        for mi in range(num_valid_moves):
            meta = move_metas[mi]
            plan.append(('anim', max(1, n_anim), mi, {'from': meta['from'], 'to': meta['to'], 'piece_obj': meta['piece_obj'], 'captured': meta['captured']}))
            safe_hold_idx = min(mi + 1, len(usi_moves))
            plan.append(('hold', max(1, n_hold), safe_hold_idx, meta['last_move']))
        if num_valid_moves > 0:
            last_hold_frames = max(1, int(cfg.end_hold_duration * fps))
            last_meta = move_metas[-1]
            plan.append(('last_hold', last_hold_frames, len(usi_moves), last_meta['last_move']))
        if cfg.end_title_enabled: plan.append(('end', max(1, int(cfg.end_title_duration * fps))))
        return plan

    @staticmethod
    def _ffmpeg_cmd(w, h, fps, cfg, puzzle_data, output_path, audio_path=None):
        cmd = ["ffmpeg", "-y", "-f", "rawvideo", "-vcodec", "rawvideo", "-s", f"{w}x{h}", "-pix_fmt", "bgr24", "-r", str(fps), "-i", "-"]
        if audio_path: cmd.extend(["-i", audio_path])
        cmd.extend(["-c:v", "libx264", "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p", "-crf", str(cfg.ffmpeg_crf), "-preset", cfg.ffmpeg_preset, "-bf", "2", "-g", str(fps * 2), "-keyint_min", str(fps), "-sc_threshold", "0", "-movflags", "+faststart", "-metadata", f"title={puzzle_data.get('name', 'Shogi Puzzle')}"])
        if audio_path: cmd.extend(["-c:a", "aac", "-b:a", "192k", "-shortest"])
        else: cmd.append("-an")
        cmd.append(output_path); return cmd

    @staticmethod
    def _safe_close(proc):
        try: proc.stdin.close()
        except Exception: pass
        proc.terminate()

# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════
def main():
    if not HAS_SHOGI:
        print("Please install the 'shogi' library: pip install shogi")
        sys.exit(1)
        
    app = QApplication(sys.argv); app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(18, 18, 30))
    palette.setColor(QPalette.WindowText, QColor(220, 220, 230))
    palette.setColor(QPalette.Base, QColor(30, 30, 42))
    palette.setColor(QPalette.AlternateBase, QColor(34, 34, 58))
    palette.setColor(QPalette.ToolTipBase, QColor(30, 30, 46))
    palette.setColor(QPalette.ToolTipText, QColor(220, 220, 230))
    palette.setColor(QPalette.Text, QColor(220, 220, 230))
    palette.setColor(QPalette.Button, QColor(42, 42, 58))
    palette.setColor(QPalette.ButtonText, QColor(220, 220, 230))
    palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    app.setPalette(palette)
    window = MainWindow(); window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()