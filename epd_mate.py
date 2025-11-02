"""
EPD Mate Filter - single-file Windows app (PySide6 + python-chess)

Features:
- Load large EPD file (streamed, memory-friendly)
- Select Stockfish engine executable path
- Configure engine depth and number of threads
- Show number of positions in file
- Progress bar for load and analysis
- Analyze positions and keep those with mate <= mate_in_moves slider (0..12)
- Show ETA while analyzing
- Save filtered positions to a new EPD file (original not modified)

Requirements:
- Python 3.8+
- pip install python-chess PySide6
- Stockfish binary for Windows (point Engine Path to it)

Notes on performance and reliability:
- The app counts lines first (fast sequential pass) then performs analysis in a second pass.
- Uses a single engine instance for simplicity and to avoid process explosion; you can set threads in engine options.
- For heavy throughput, consider adding worker processes each with their own engine instance.
- Always closes engine and subprocesses to avoid memory leaks.

"""

import sys
import os
import time
import threading
from datetime import timedelta
import json
import re
import signal

# Qt bindings compatibility: prefer PySide6, fallback to PyQt6, PySide2 or PyQt5
try:
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QPushButton, QLabel, QProgressBar, QFileDialog, QSpinBox, QSlider,
        QLineEdit, QTextEdit, QMessageBox, QCheckBox, QComboBox, QDialog
    )
    from PySide6.QtCore import Qt, QTimer, Slot, QEvent
    QT_BINDING = 'PySide6'
except Exception:
    try:
        from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QPushButton, QLabel, QProgressBar, QFileDialog, QSpinBox, QSlider,
        QLineEdit, QTextEdit, QMessageBox, QCheckBox, QComboBox, QDialog
        )
        from PyQt6.QtCore import Qt, QTimer, QEvent
        # PyQt6 uses different slot decorator name
        from PyQt6.QtCore import pyqtSlot as Slot
        QT_BINDING = 'PyQt6'
    except Exception:
        try:
            from PySide2.QtWidgets import (
                QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                QPushButton, QLabel, QProgressBar, QFileDialog, QSpinBox, QSlider,
                QLineEdit, QTextEdit, QMessageBox, QCheckBox, QComboBox, QDialog
            )
            from PySide2.QtCore import Qt, QTimer, Slot, QEvent
            QT_BINDING = 'PySide2'
        except Exception:
            try:
                from PyQt5.QtWidgets import (
                QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                QPushButton, QLabel, QProgressBar, QFileDialog, QSpinBox, QSlider,
                QLineEdit, QTextEdit, QMessageBox, QCheckBox, QComboBox, QDialog
                )
                from PyQt5.QtCore import Qt, QTimer, QEvent
                from PyQt5.QtCore import pyqtSlot as Slot
                QT_BINDING = 'PyQt5'
            except Exception:
                raise ImportError("No suitable Qt binding found: install PySide6, PyQt6, PySide2 or PyQt5")

import chess
import chess.engine

# Small event wrapper to post callables from background threads to the Qt main thread
class _CallableEvent(QEvent):
    def __init__(self, callable_):
        super().__init__(QEvent.Type(QEvent.registerEventType()))
        self.callable = callable_

# --- Debug logging setup ---
DEBUG_LOG = "debug.log"

def debug_log(msg):
    """Write message to debug log (and console)"""
    timestamp = time.strftime("%H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    try:
        with open(DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

# Clear the previous log at startup
open(DEBUG_LOG, "w").close()
debug_log("=== New Run Started ===")


# Engine default settings for search depth and threads
DEFAULT_DEPTH = 20
DEFAULT_THREADS = 1
SETTINGS_FILE = 'epd_mate_settings.json'


def _read_settings_data():
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as sf:
                return json.load(sf)
    except Exception:
        pass
    return {}


def _write_settings_data(data):
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as sf:
            json.dump(data, sf, indent=2)
    except Exception:
        pass


def update_settings(updates):
    data = _read_settings_data()
    try:
        data.update(updates or {})
    except Exception:
        # fallback to rewriting updates only if data isn't a dict
        data = updates or {}
    _write_settings_data(data)

# Analyzer thread to analyze positions sequentially.
class AnalyzerThread(threading.Thread):
    """Background worker to analyze positions sequentially."""
    def __init__(self, input_path, output_path, engine_path, depth, threads, mate_limit, add_solution, progress_callback, eta_callback, log_callback, stop_event):
        super().__init__()
        self.input_path = input_path
        self.output_path = output_path
        self.engine_path = engine_path
        self.depth = depth
        self.threads = threads
        self.mate_limit = mate_limit
        # whether to add mate solution to output (UI checkbox)
        self.add_solution = bool(add_solution)
        self.progress_callback = progress_callback
        self.eta_callback = eta_callback
        self.log_callback = log_callback
        self.stop_event = stop_event
        # Keep initialization lightweight; heavy work runs in run().
        self._engine = None
        self._total_positions = 0
        self._processed = 0
        self._kept = 0

    def run(self):
        try:
            # Start engine
            self.log_callback(f"Starting engine: {self.engine_path} (depth={self.depth}, threads={self.threads})")
            engine = chess.engine.SimpleEngine.popen_uci(self.engine_path)
            self._engine = engine
            # apply options if available
            try:
                engine.configure({'Threads': max(1, int(self.threads))})
            except Exception:
                # Some engines might reject unknown options
                pass

            total_positions = 0
            # First pass: count lines
            with open(self.input_path, 'r', encoding='utf-8', errors='ignore') as f:
                for _ in f:
                    total_positions += 1
            if total_positions == 0:
                self.log_callback('Input file is empty.')
                try:
                    engine.quit()
                except Exception:
                    pass
                return

            self._total_positions = total_positions
            self.log_callback(f"Total positions: {total_positions}")

            # Prepare output file
            out_dir = os.path.dirname(self.output_path)
            if out_dir and not os.path.exists(out_dir):
                os.makedirs(out_dir, exist_ok=True)

            processed = 0
            kept = 0
            start_time = time.time()
            with open(self.input_path, 'r', encoding='utf-8', errors='ignore') as fin, open(self.output_path, 'w', encoding='utf-8') as fout:
                for line in fin:
                    if self.stop_event.is_set():
                        self.log_callback('Analysis cancelled by user.')
                        break

                    fen_line = line.strip()
                    processed += 1
                    self._processed = processed

                    # Update progress and ETA
                    elapsed = time.time() - start_time
                    avg = elapsed / processed
                    remaining = total_positions - processed
                    eta = remaining * avg
                    try:
                        self.progress_callback(int(processed / total_positions * 100), processed, total_positions, kept)
                    except Exception:
                        pass

                    try:
                        self.eta_callback(eta)
                    except Exception:
                        pass

                    if not fen_line:
                        continue

                    fields = fen_line.split()
                    if len(fields) >= 6:
                        candidate_fen = ' '.join(fields[:6])
                    else:
                        candidate_fen = fen_line

                    # Validate fen
                    try:
                        board = chess.Board(candidate_fen)
                    except Exception:
                        # invalid fen, skip
                        self.log_callback(f"Skipping invalid FEN at line {processed}")
                        continue

                    # Analyse with engine
                    try:
                        limit = chess.engine.Limit(depth=self.depth)
                        info = engine.analyse(board, limit)
                        score = info.get('score')
                        mate = None
                        if score is not None:
                            # 1) Try direct mate() (some Score types support it)
                            try:
                                mate = score.mate()
                            except Exception:
                                mate = None

                            # 2) Try POV score if available
                            if mate is None:
                                try:
                                    if hasattr(score, 'pov'):
                                        try:
                                            pov = score.pov(board.turn)
                                        except Exception:
                                            try:
                                                pov = score.pov(chess.WHITE if board.turn else chess.BLACK)
                                            except Exception:
                                                pov = None
                                        if pov is not None and hasattr(pov, 'mate'):
                                            try:
                                                mate = pov.mate()
                                            except Exception:
                                                mate = None
                                except Exception:
                                    mate = None

                            # 3) Last resort: parse textual representation like "mate 3"
                            if mate is None:
                                try:
                                    s = str(score)
                                    m = re.search(r'mate\s*([+-]?\d+)', s)
                                    if m:
                                        mate = int(m.group(1))
                                except Exception:
                                    mate = None
                        if mate is not None:
                            mate_moves = abs(mate)
                            # Keep if mate_moves within limit and positive
                            if 1 <= mate_moves <= self.mate_limit:
                                output_line = line.rstrip('\n')

                                try:
                                    pv_raw = info.get('pv') or []
                                except Exception:
                                    pv_raw = []

                                pv_slice = []
                                move_ucis = []
                                mate_index = None

                                if pv_raw:
                                    board_cp = board.copy()
                                    for idx, mv in enumerate(pv_raw):
                                        pv_slice.append(mv)
                                        try:
                                            uci = mv.uci()
                                        except Exception:
                                            uci = str(mv)
                                        move_ucis.append(uci)
                                        try:
                                            board_cp.push(mv)
                                        except Exception:
                                            break
                                        if board_cp.is_checkmate():
                                            mate_index = idx
                                            break

                                annotated_move_ucis = move_ucis.copy()
                                if annotated_move_ucis:
                                    mark_idx = mate_index if mate_index is not None else len(annotated_move_ucis) - 1
                                    try:
                                        annotated_move_ucis[mark_idx] = annotated_move_ucis[mark_idx] + '#'
                                    except Exception:
                                        pass

                                if self.add_solution and annotated_move_ucis:
                                    moves_str = ' '.join(annotated_move_ucis)
                                    # use 'sol' token to indicate solution moves (EPD operand quoted)
                                    output_line += f' ; sol "{moves_str}";'
                                    self.log_callback(f"Added solution moves ({len(annotated_move_ucis)}) for line {processed}: {moves_str}")
                                    # always append theme with mate distance so downstream tools can pick it up
                                    try:
                                        output_line += f' ; theme "mate {mate_moves}";'
                                    except Exception:
                                        pass

                                fout.write(output_line + '\n')
                                kept += 1
                                self._kept = kept
                                self.log_callback(f"Kept line {processed}: mate in {mate_moves}")
                                debug_log(f"Kept line {processed}: mate in {mate_moves} (total kept = {kept})")
                                try:
                                    self.progress_callback(int(processed / total_positions * 100), processed, total_positions, kept)
                                except Exception:
                                    pass

                    except Exception as e:
                        self.log_callback(f"Engine error on line {processed}: {e}")
                        # attempt to continue
                        continue

            # Close engine
            try:
                engine.quit()
            except Exception:
                pass

            total_elapsed = time.time() - start_time
            self.log_callback(f"Finished. Processed {processed}/{total_positions}, kept {kept}. Time: {timedelta(seconds=int(total_elapsed))}")
            # Final progress update
            try:
                self.progress_callback(100, processed, total_positions, kept)
            except Exception:
                pass
            try:
                self.eta_callback(0)
            except Exception:
                pass

        except Exception as e:
            try:
                self.log_callback(f"Fatal error: {e}")
            except Exception:
                pass


_SOL_PATTERN = re.compile(r';\s*sol\s*"([^"]+)"', re.IGNORECASE)
_THEME_PATTERN = re.compile(r';\s*theme\s*"([^"]+)"', re.IGNORECASE)
_MATE_PATTERN = re.compile(r'mate\s*([+-]?\d+)', re.IGNORECASE)
_MOVE_SUFFIX_PATTERN = re.compile(r'[+#?!]+$', re.IGNORECASE)


def _extract_solution_moves(solution_text):
    tokens = []
    if not solution_text:
        return tokens
    for raw in solution_text.strip().split():
        token = raw.strip()
        if token:
            tokens.append(token)
    return tokens


def _extract_mate_moves(theme_text):
    if not theme_text:
        return None
    match = _MATE_PATTERN.search(theme_text)
    if match:
        try:
            return abs(int(match.group(1)))
        except Exception:
            return None
    return None


def _sanitize_uci(move_text):
    if not move_text:
        return ''
    return _MOVE_SUFFIX_PATTERN.sub('', move_text.strip())


def _build_puzzle_entry(board, solution_moves, mate_moves, fix_move_order, line_number=None, log_callback=None):
    """
    Build one JSON puzzle entry.
    If fix_move_order=True, ensure the winning side is to move.
    If the first move belongs to the losing side, apply it to the board
    so the FEN reflects that move having been played.
    """
    try:
        board_sim = board.copy()
        applied_moves = []
        valid_tokens = []
        
        # Parse and validate all moves, skipping invalid ones
        for token in solution_moves:
            mv_uci = _sanitize_uci(token)
            if not mv_uci:
                if log_callback:
                    log_callback(f"Line {line_number or '?'}: skipping empty move '{token}'")
                continue
            try:
                mv = chess.Move.from_uci(mv_uci)
            except Exception as exc:
                if log_callback:
                    log_callback(f"Line {line_number or '?'}: skipping invalid move '{token}' ({exc})")
                continue
            if mv not in board_sim.legal_moves:
                if log_callback:
                    log_callback(f"Line {line_number or '?'}: skipping illegal move '{token}' (not in legal moves)")
                continue
            board_sim.push(mv)
            applied_moves.append(mv_uci)
            valid_tokens.append(token)  # Keep original token format with suffixes

        if not applied_moves:
            if log_callback:
                log_callback(f"Line {line_number or '?'}: no valid moves found in solution. Original moves: {solution_moves[:10]}")
            # Fallback: if no moves validated, still try to create entry with original moves
            # This handles cases where moves might be valid but validation failed
            if not solution_moves:
                return None
            # Fallback: try to determine winning color from move count
            # If mate_moves is odd, the side that starts wins; if even, the other side wins
            # But simpler: assume the side that makes the last move (mate) is the winner
            board_for_json = board.copy()
            moves_for_json = solution_moves.copy()
            
            # Determine winning color: if mate_moves is provided, count moves
            # The side that delivers mate is the winner
            if mate_moves:
                # Count which side makes the mate move
                # If mate_moves is odd, starting side wins; if even, other side wins
                starting_color = board.turn
                if mate_moves % 2 == 1:
                    winning_color = starting_color
                else:
                    winning_color = not starting_color
            else:
                # Default: assume starting side wins (common case)
                winning_color = board.turn
            
            if fix_move_order:
                first_move_color = board_for_json.turn
                first_move_uci = _sanitize_uci(solution_moves[0]) if solution_moves else None
                if first_move_uci:
                    try:
                        mv = chess.Move.from_uci(first_move_uci)
                        if mv in board_for_json.legal_moves:
                            board_for_json.push(mv)
                            moves_for_json = solution_moves[1:]
                            if log_callback:
                                log_callback(f"Line {line_number or '?'}: fallback mode - baked first move {first_move_uci} into FEN.")
                    except Exception:
                        pass
                board_for_json.turn = winning_color
            
            return {
                "fen": board_for_json.fen(),
                "solution": moves_for_json,
                "moves_to_mate": mate_moves,
                "elo": 1200,
                "solved": 0,
                "failed": 0
            }

        # Determine winner (side that delivered mate)
        winning_color = not board_sim.turn if board_sim.is_checkmate() else board.turn

        board_for_json = board.copy()
        moves_for_json = valid_tokens.copy()  # Use valid tokens preserving original format

        if fix_move_order:
            # Identify who moves first in original FEN
            first_move_color = board_for_json.turn
            
            # Get the first valid move that was actually applied
            if valid_tokens and applied_moves:
                first_move_uci = applied_moves[0]  # Use sanitized version for move object
                first_token = valid_tokens[0]  # Use original token for output

                # If the first move is not by the winning color, apply it to board
                if first_move_color != winning_color:
                    try:
                        mv = chess.Move.from_uci(first_move_uci)
                        if mv in board_for_json.legal_moves:
                            board_for_json.push(mv)
                            moves_for_json = valid_tokens[1:]  # Remove first move from solution
                            if log_callback:
                                log_callback(f"Line {line_number or '?'}: baked first move {first_token} into FEN.")
                    except Exception as exc:
                        if log_callback:
                            log_callback(f"Line {line_number or '?'}: failed to bake first move ({exc})")

            # Ensure correct side to move (winner)
            board_for_json.turn = winning_color

        return {
            "fen": board_for_json.fen(),
            "solution": moves_for_json,
            "moves_to_mate": mate_moves,
            "elo": 1200,
            "solved": 0,
            "failed": 0
        }

    except Exception as exc:
        if log_callback:
            log_callback(f"Line {line_number or '?'}: build failed ({exc})")
        return None


def _parse_puzzle_from_line(raw_line, line_number, fix_move_order, log_callback=None):
    sol_match = _SOL_PATTERN.search(raw_line)
    if not sol_match:
        if log_callback and line_number <= 3:  # Log first few lines for debugging
            log_callback(f"Line {line_number}: no 'sol' operand found. Line preview: {raw_line[:100]}")
        return None

    solution_moves = _extract_solution_moves(sol_match.group(1))
    if not solution_moves:
        if log_callback:
            log_callback(f"Line {line_number}: 'sol' operand is empty.")
        return None

    base_segment = raw_line.split(';', 1)[0].strip()
    fields = base_segment.split()
    if len(fields) < 4:
        if log_callback:
            log_callback(f"Line {line_number}: not enough FEN fields to parse board.")
        return None
    fen_fields = fields[:6] if len(fields) >= 6 else fields
    fen = ' '.join(fen_fields)

    try:
        board = chess.Board(fen)
    except Exception as exc:
        if log_callback:
            log_callback(f"Line {line_number}: invalid FEN ({exc}).")
        return None

    mate_moves = None
    theme_match = _THEME_PATTERN.search(raw_line)
    if theme_match:
        mate_moves = _extract_mate_moves(theme_match.group(1))
    if mate_moves is None:
        mate_moves = len(solution_moves)

    entry = _build_puzzle_entry(board, solution_moves, mate_moves, fix_move_order, line_number=line_number, log_callback=log_callback)
    if not entry and log_callback and line_number <= 3:
        log_callback(f"Line {line_number}: _build_puzzle_entry returned None. Solution moves: {solution_moves[:5]}")
    return entry


def generate_json_from_epd(source_path, fix_move_order=False, progress_callback=None, log_callback=None, stop_event=None):
    total_lines = 0
    try:
        with open(source_path, 'r', encoding='utf-8', errors='ignore') as counter:
            for _ in counter:
                total_lines += 1
    except FileNotFoundError:
        raise FileNotFoundError(f"Source EPD not found: {source_path}")

    if total_lines == 0:
        raise ValueError('Source EPD file is empty.')

    puzzles = []
    processed = 0
    kept = 0
    cancelled = False

    try:
        with open(source_path, 'r', encoding='utf-8', errors='ignore') as fin:
            for line_number, raw_line in enumerate(fin, 1):
                if stop_event and stop_event.is_set():
                    cancelled = True
                    if log_callback:
                        log_callback('Export cancelled by user request.')
                    break

                processed = line_number
                stripped = raw_line.strip()
                if stripped:
                    entry = _parse_puzzle_from_line(stripped, line_number, fix_move_order, log_callback=log_callback)
                    if entry:
                        puzzles.append(entry)
                        kept += 1
                        if log_callback:
                            log_callback(f"Line {line_number}: added puzzle (mate in {entry['moves_to_mate']}).")

                if progress_callback:
                    pct = int(line_number / total_lines * 100)
                    progress_callback(pct, line_number, total_lines, kept)
    finally:
        if progress_callback:
            progress_callback(100, processed, total_lines, kept)

    payload = {
        'theme': 'Mates',
        'pattern': 'Mates',
        'puzzles': puzzles
    }

    return payload, processed, kept, cancelled


class JsonExportWorker(threading.Thread):
    def __init__(self, source_path, dest_path, fix_move_order, progress_callback, log_callback, finished_callback, stop_event):
        super().__init__()
        self.source_path = source_path
        self.dest_path = dest_path
        self.fix_move_order = fix_move_order
        self.progress_callback = progress_callback
        self.log_callback = log_callback
        self.finished_callback = finished_callback
        self.stop_event = stop_event

    def run(self):
        try:
            payload, processed, kept, cancelled = generate_json_from_epd(
                self.source_path,
                fix_move_order=self.fix_move_order,
                progress_callback=self.progress_callback,
                log_callback=self.log_callback,
                stop_event=self.stop_event
            )

            if cancelled:
                if self.finished_callback:
                    self.finished_callback(False, 'Export cancelled.', kept)
                return

            dest_dir = os.path.dirname(self.dest_path)
            if dest_dir and not os.path.exists(dest_dir):
                os.makedirs(dest_dir, exist_ok=True)

            with open(self.dest_path, 'w', encoding='utf-8') as jf:
                json.dump(payload, jf, indent=2)

            if self.log_callback:
                self.log_callback(f"Saved JSON with {kept} puzzles to {self.dest_path} (processed {processed} lines).")
            if self.finished_callback:
                self.finished_callback(True, self.dest_path, kept)

        except Exception as exc:
            if self.log_callback:
                self.log_callback(f'JSON export failed: {exc}')
            if self.finished_callback:
                self.finished_callback(False, str(exc), 0)


class JsonExportDialog(QDialog):
    def __init__(self, parent=None, default_source='', default_output=''):
        super().__init__(parent)
        self.setWindowTitle('Export JSON')
        self.setMinimumSize(640, 420)

        self.worker = None
        self.stop_event = threading.Event()

        self._build_ui()
        self._load_settings(default_source, default_output)

    def _build_ui(self):
        layout = QVBoxLayout()

        src_layout = QHBoxLayout()
        src_layout.addWidget(QLabel('Source EPD:'))
        self.source_line = QLineEdit()
        btn_src = QPushButton('Browse...')
        btn_src.clicked.connect(self._browse_source)
        src_layout.addWidget(self.source_line)
        src_layout.addWidget(btn_src)
        layout.addLayout(src_layout)

        dest_layout = QHBoxLayout()
        dest_layout.addWidget(QLabel('Destination JSON:'))
        self.dest_line = QLineEdit()
        btn_dest = QPushButton('Save As...')
        btn_dest.clicked.connect(self._browse_dest)
        dest_layout.addWidget(self.dest_line)
        dest_layout.addWidget(btn_dest)
        layout.addLayout(dest_layout)

        options_layout = QHBoxLayout()
        self.fix_move_order_check = QCheckBox('Fix move order (winner to move)')
        self.fix_move_order_check.setChecked(True)
        options_layout.addWidget(self.fix_move_order_check)
        options_layout.addStretch()
        layout.addLayout(options_layout)

        self.status_label = QLabel('Status: Idle')
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        layout.addWidget(self.status_label)
        layout.addWidget(self.progress_bar)

        layout.addWidget(QLabel('Log:'))
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.export_btn = QPushButton('Export')
        self.export_btn.clicked.connect(self.start_export)
        self.cancel_btn = QPushButton('Cancel')
        self.cancel_btn.clicked.connect(self.cancel_export)
        self.cancel_btn.setEnabled(False)
        self.close_btn = QPushButton('Close')
        self.close_btn.clicked.connect(self.close)
        btn_layout.addWidget(self.export_btn)
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.close_btn)
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def _load_settings(self, default_source='', default_output=''):
        data = _read_settings_data()
        source = data.get('json_source') or default_source
        dest = data.get('json_output') or default_output
        fix = data.get('json_fix_move_order')

        self.source_line.setText(source or '')
        self.dest_line.setText(dest or '')
        if fix is None:
            fix = True
        self.fix_move_order_check.setChecked(bool(fix))

    def _browse_source(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Select Source EPD', filter='EPD Files (*.epd);;All Files (*)')
        if path:
            self.source_line.setText(path)
            self._suggest_dest_from_source()

    def _browse_dest(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Save JSON File', filter='JSON Files (*.json);;All Files (*)')
        if path:
            if not path.lower().endswith('.json'):
                path += '.json'
            self.dest_line.setText(path)

    def _suggest_dest_from_source(self):
        src = self.source_line.text().strip()
        if not src:
            return
        base, _ = os.path.splitext(src)
        suggested = base + '.json'
        if not self.dest_line.text().strip():
            self.dest_line.setText(suggested)

    def start_export(self):
        if self.worker and self.worker.is_alive():
            return

        source_path = self.source_line.text().strip()
        if not source_path or not os.path.exists(source_path):
            QMessageBox.warning(self, 'Export JSON', 'Please select a valid source EPD file.')
            return

        dest_path = self.dest_line.text().strip()
        if not dest_path:
            QMessageBox.warning(self, 'Export JSON', 'Please choose where to save the JSON file.')
            return

        dest_dir = os.path.dirname(dest_path)
        if dest_dir and not os.path.exists(dest_dir):
            try:
                os.makedirs(dest_dir, exist_ok=True)
            except Exception as exc:
                QMessageBox.warning(self, 'Export JSON', f'Unable to create destination folder: {exc}')
                return

        self.stop_event.clear()
        self.progress_bar.setValue(0)
        self.status_label.setText('Status: Exporting...')
        self.log.clear()
        self.export_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)

        fix_move_order = self.fix_move_order_check.isChecked()
        self._save_settings(source_path, dest_path, fix_move_order)

        self.worker = JsonExportWorker(
            source_path=source_path,
            dest_path=dest_path,
            fix_move_order=fix_move_order,
            progress_callback=self.on_progress,
            log_callback=self.append_log,
            finished_callback=self.on_finished,
            stop_event=self.stop_event
        )
        self.worker.start()

    def cancel_export(self):
        if self.worker and self.worker.is_alive():
            self.stop_event.set()
            self.status_label.setText('Status: Cancelling...')
            self.cancel_btn.setEnabled(False)

    def on_progress(self, pct, processed, total, kept):
        def upd():
            self.progress_bar.setValue(pct)
            self.status_label.setText(f'Status: {processed}/{total} lines, {kept} puzzles')
        QApplication.instance().postEvent(self, _CallableEvent(upd))

    def on_finished(self, success, message, kept):
        def upd():
            self.worker = None
            self.cancel_btn.setEnabled(False)
            self.export_btn.setEnabled(True)
            if success:
                self.status_label.setText(f'Status: Completed ({kept} puzzles).')
                QMessageBox.information(self, 'Export JSON', f'JSON file saved to:\n{message}')
                parent = self.parent()
                if parent and hasattr(parent, 'append_log'):
                    parent.append_log(f'JSON export saved to {message}')
            else:
                current = 'Cancelled' if self.stop_event.is_set() else 'Failed'
                self.status_label.setText(f'Status: {current}.')
                if message:
                    QMessageBox.warning(self, 'Export JSON', message)
            self.stop_event.clear()
        QApplication.instance().postEvent(self, _CallableEvent(upd))

    def append_log(self, text):
        def upd():
            self.log.append(text)
            self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())
        QApplication.instance().postEvent(self, _CallableEvent(upd))

    def _save_settings(self, source, dest, fix_move_order):
        update_settings({
            'json_source': source or '',
            'json_output': dest or '',
            'json_fix_move_order': bool(fix_move_order)
        })

    def event(self, e):
        if isinstance(e, _CallableEvent):
            e.callable()
            return True
        return super().event(e)

    def closeEvent(self, event):
        if self.worker and self.worker.is_alive():
            QMessageBox.warning(self, 'Export JSON', 'Please wait for the export to finish or cancel it before closing.')
            event.ignore()
            return
        super().closeEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('EPD Mate Filter')
        self.setMinimumSize(800, 480)

        self.engine_path = ''
        self.input_path = ''
        self.output_path = ''
        self.analyzer = None
        self.stop_event = threading.Event()

        self._build_ui()
        # load last used paths if available
        try:
            self.load_settings()
        except Exception:
            pass

    def _build_ui(self):
        w = QWidget()
        layout = QVBoxLayout()

        # File selectors
        file_layout = QHBoxLayout()
        self.input_line = QLineEdit()
        btn_browse = QPushButton('Open EPD')
        btn_browse.clicked.connect(self.browse_input)
        file_layout.addWidget(QLabel('EPD File:'))
        file_layout.addWidget(self.input_line)
        file_layout.addWidget(btn_browse)

        engine_layout = QHBoxLayout()
        self.engine_line = QLineEdit()
        btn_engine = QPushButton('Select Engine')
        btn_engine.clicked.connect(self.browse_engine)
        engine_layout.addWidget(QLabel('Engine:'))
        engine_layout.addWidget(self.engine_line)
        engine_layout.addWidget(btn_engine)

        layout.addLayout(file_layout)
        layout.addLayout(engine_layout)

        layout.addWidget(QLabel('<b>EPD Output</b>'))
        output_layout = QHBoxLayout()
        self.output_line = QLineEdit()
        btn_output = QPushButton('Save As')
        btn_output.clicked.connect(self.browse_output)
        output_layout.addWidget(QLabel('Output EPD:'))
        output_layout.addWidget(self.output_line)
        output_layout.addWidget(btn_output)
        layout.addLayout(output_layout)

        epd_opts_layout = QHBoxLayout()
        self.add_solution_checkbox = QCheckBox('Add mate solution')
        self.add_solution_checkbox.setChecked(True)
        epd_opts_layout.addWidget(self.add_solution_checkbox)
        epd_opts_layout.addStretch()
        layout.addLayout(epd_opts_layout)

        export_layout = QHBoxLayout()
        export_layout.addStretch()
        self.export_json_btn = QPushButton('Export JSON...')
        self.export_json_btn.clicked.connect(self.open_json_export_dialog)
        export_layout.addWidget(self.export_json_btn)
        layout.addLayout(export_layout)

        # === Engine Settings ===
        layout.addWidget(QLabel("<b>Engine Settings</b>"))

        engine_opts = QHBoxLayout()
        self.depth_spin = QSpinBox()
        self.depth_spin.setRange(1, 128)
        self.depth_spin.setValue(DEFAULT_DEPTH)
        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(1, 16)
        self.threads_spin.setValue(DEFAULT_THREADS)

        engine_opts.addWidget(QLabel('Depth:'))
        engine_opts.addWidget(self.depth_spin)
        engine_opts.addWidget(QLabel('Threads:'))
        engine_opts.addWidget(self.threads_spin)
        layout.addLayout(engine_opts)

        # === Mate Finder ===
        layout.addWidget(QLabel("<b>Mate Finder</b>"))

        mate_layout = QHBoxLayout()
        self.mate_slider = QSlider(Qt.Horizontal)
        self.mate_slider.setRange(0, 12)
        self.mate_slider.setValue(6)
        self.mate_label = QLabel('Mate <= 6')
        self.mate_slider.valueChanged.connect(lambda v: self.mate_label.setText(f"Mate <= {v}"))

        mate_layout.addWidget(self.mate_label)
        mate_layout.addWidget(self.mate_slider)
        layout.addLayout(mate_layout)


        # Controls
        ctrl_layout = QHBoxLayout()
        self.count_label = QLabel('Positions: 0')
        self.eta_label = QLabel('ETA: N/A')
        self.kept_label = QLabel('Kept: 0')
        self.load_progress = QProgressBar()
        self.load_progress.setValue(0)
        self.analyze_btn = QPushButton('Analyze')
        self.analyze_btn.clicked.connect(self.start_analyze)
        self.cancel_btn = QPushButton('Cancel')
        self.cancel_btn.clicked.connect(self.cancel_analysis)
        self.cancel_btn.setEnabled(False)

        ctrl_layout.addWidget(self.count_label)
        ctrl_layout.addWidget(self.eta_label)
        ctrl_layout.addWidget(self.kept_label)
        ctrl_layout.addWidget(self.load_progress)
        ctrl_layout.addWidget(self.analyze_btn)
        ctrl_layout.addWidget(self.cancel_btn)

        layout.addLayout(ctrl_layout)

        # Log
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(QLabel('Log:'))
        layout.addWidget(self.log)

        # Show current engine search line at the bottom
        self.engine_status_label = QLabel('Engine Status: N/A')
        layout

        w.setLayout(layout)
        self.setCentralWidget(w)

    def load_settings(self):
        data = _read_settings_data()
        try:
            inp = data.get('last_input')
            eng = data.get('last_engine')
            out = data.get('last_output')
            if inp and os.path.exists(inp):
                self.input_path = inp
                self.input_line.setText(inp)
                cnt = self.count_positions(inp)
                self.count_label.setText(f'Positions: {cnt}')
                # suggest output if none
                if not out:
                    base = os.path.splitext(inp)[0]
                    out = base + '_mates.epd'
            if eng and os.path.exists(eng):
                self.engine_path = eng
                self.engine_line.setText(eng)
            if out:
                self.output_path = out
                self.output_line.setText(out)
        except Exception:
            # ignore settings errors
            pass

    def save_settings(self):
        update_settings({
            'last_input': self.input_line.text() or '',
            'last_engine': self.engine_line.text() or '',
            'last_output': self.output_line.text() or ''
        })

    @Slot()
    def browse_input(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Open EPD', filter='EPD Files (*.epd);;All Files (*)')
        if path:
            self.input_path = path
            self.input_line.setText(path)
            # count lines quickly
            count = self.count_positions(path)
            self.count_label.setText(f'Positions: {count}')

            # suggest default output in same folder
            base = os.path.splitext(path)[0]
            suggested = base + '_mates.epd'
            self.output_line.setText(suggested)
            self.output_path = suggested
            # save setting
            try:
                self.save_settings()
            except Exception:
                pass

    @Slot()
    def browse_engine(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Select Engine', filter='Executables (*.exe);;All Files (*)')
        if path:
            self.engine_path = path
            self.engine_line.setText(path)
            try:
                self.save_settings()
            except Exception:
                pass

    @Slot()
    def browse_output(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Save Filtered EPD', filter='EPD Files (*.epd);;All Files (*)')
        if path:
            self.output_path = path
            self.output_line.setText(path)
            try:
                self.save_settings()
            except Exception:
                pass

    @Slot()
    def open_json_export_dialog(self):
        default_source = ''
        if self.output_path and os.path.exists(self.output_path):
            default_source = self.output_path
        elif self.input_path and os.path.exists(self.input_path):
            default_source = self.input_path

        default_output = ''
        if default_source:
            base, _ = os.path.splitext(default_source)
            default_output = base + '.json'

        dialog = JsonExportDialog(self, default_source=default_source, default_output=default_output)
        dialog.exec()
    
    def count_positions(self, path):
        # fast count lines without loading file fully
        try:
            cnt = 0
            with open(path, 'rb') as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b''):
                    cnt += chunk.count(b'\n')
            return cnt
        except Exception:
            return 0

    @Slot()
    def start_analyze(self):
        if not self.input_line.text() or not os.path.exists(self.input_line.text()):
            QMessageBox.warning(self, 'No input', 'Please select a valid input EPD file.')
            return
        if not self.engine_line.text() or not os.path.exists(self.engine_line.text()):
            QMessageBox.warning(self, 'No engine', 'Please select a valid Stockfish (or UCI) engine executable.')
            return
        if not self.output_line.text():
            QMessageBox.warning(self, 'No output', 'Please choose an output file path.')
            return

        self.input_path = self.input_line.text()
        self.engine_path = self.engine_line.text()
        self.output_path = self.output_line.text()

        # disable UI controls
        self.analyze_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.stop_event.clear()
        self.load_progress.setValue(0)
        self.log.clear()

        depth = int(self.depth_spin.value())
        threads = int(self.threads_spin.value())
        mate_limit = int(self.mate_slider.value())

        # start background thread
        self.analyzer = AnalyzerThread(
            input_path=self.input_path,
            output_path=self.output_path,
            engine_path=self.engine_path,
            depth=depth,
            threads=threads,
            mate_limit=mate_limit,
            add_solution=self.add_solution_checkbox.isChecked(),
            progress_callback=self.on_progress,
            eta_callback=self.on_eta,
            log_callback=self.append_log,
            stop_event=self.stop_event
        )
        self.analyzer.start()

        # Update engine label
        self.engine_status_label.setText(f"Engine: {os.path.basename(self.engine_path)}")
        debug_log(f"Analysis started with engine: {self.engine_path}")

        # small timer to poll thread status and re-enable UI when done
        self.poll_timer = QTimer()
        self.poll_timer.setInterval(500)
        self.poll_timer.timeout.connect(self.poll_thread)
        self.poll_timer.start()

    @Slot()
    def cancel_analysis(self):
        self.stop_event.set()
        self.append_log('Cancellation requested...')
        self.cancel_btn.setEnabled(False)

    def poll_thread(self):
        if self.analyzer and not self.analyzer.is_alive():
            self.poll_timer.stop()
            self.analyzer = None
    def on_progress(self, pct, processed, total, kept):
        # Post a callable event to update progress UI from the analyzer thread
        def upd():
            self.load_progress.setValue(pct)
            self.count_label.setText(f'Positions: {processed}/{total}')
            self.kept_label.setText(f'Kept: {kept}')
        QApplication.instance().postEvent(self, _CallableEvent(upd))

    def on_eta(self, seconds_left):
        def upd():
            if seconds_left <= 0:
                self.eta_label.setText('ETA: 0s')
            else:
                self.eta_label.setText('ETA: ' + str(timedelta(seconds=int(seconds_left))))
        QApplication.instance().postEvent(self, _CallableEvent(upd))

    def append_log(self, text):
        def upd():
            self.log.append(text)
            # auto-scroll to bottom
            self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())
        QApplication.instance().postEvent(self, _CallableEvent(upd))

    # to receive posted callables
    def event(self, e):
        if isinstance(e, _CallableEvent):
            e.callable()
            return True
        return super().event(e)


def main():
    # Allow Ctrl+C to kill the app
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = QApplication(sys.argv)

    # Timer to allow Python interpreter to run and process signals
    timer = QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None)  # Let the interpreter run

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
