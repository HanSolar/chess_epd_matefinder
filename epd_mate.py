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
from pathlib import Path
from datetime import timedelta
import json
import re

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QProgressBar, QFileDialog, QSpinBox, QSlider,
    QLineEdit, QTextEdit, QMessageBox, QCheckBox, QComboBox
)
from PySide6.QtCore import Qt, QTimer, Slot

import chess
import chess.engine

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



DEFAULT_DEPTH = 20
DEFAULT_THREADS = 1
SETTINGS_FILE = 'epd_mate_settings.json'


class AnalyzerThread(threading.Thread):
    """Background worker to analyze positions sequentially."""
    def __init__(self, input_path, output_path, engine_path, depth, threads, mate_limit, progress_callback, eta_callback, log_callback, stop_event):
        super().__init__()
        self.input_path = input_path
        self.output_path = output_path
        self.engine_path = engine_path
        self.depth = depth
        self.threads = threads
        self.mate_limit = mate_limit
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
                                fout.write(line.rstrip('\n') + '\n')
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

        output_layout = QHBoxLayout()
        self.output_line = QLineEdit()
        btn_output = QPushButton('Save As')
        btn_output.clicked.connect(self.browse_output)
        output_layout.addWidget(QLabel('Output EPD:'))
        output_layout.addWidget(self.output_line)
        output_layout.addWidget(btn_output)

        layout.addLayout(file_layout)
        layout.addLayout(engine_layout)
        layout.addLayout(output_layout)

        # Options
        opts_layout = QHBoxLayout()
        self.depth_spin = QSpinBox()
        self.depth_spin.setRange(1, 128)
        self.depth_spin.setValue(DEFAULT_DEPTH)
        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(1, 16)
        self.threads_spin.setValue(DEFAULT_THREADS)
        self.mate_slider = QSlider(Qt.Horizontal)
        self.mate_slider.setRange(0, 12)
        self.mate_slider.setValue(6)
        self.mate_label = QLabel('Mate <= 6')
        self.mate_slider.valueChanged.connect(lambda v: self.mate_label.setText(f"Mate <= {v}"))

        opts_layout.addWidget(QLabel('Depth:'))
        opts_layout.addWidget(self.depth_spin)
        opts_layout.addWidget(QLabel('Threads:'))
        opts_layout.addWidget(self.threads_spin)
        opts_layout.addWidget(self.mate_label)
        opts_layout.addWidget(self.mate_slider)

        layout.addLayout(opts_layout)

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
        try:
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, 'r', encoding='utf-8') as sf:
                    data = json.load(sf)
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
        try:
            data = {
                'last_input': self.input_line.text() or '',
                'last_engine': self.engine_line.text() or '',
                'last_output': self.output_line.text() or ''
            }
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as sf:
                json.dump(data, sf, indent=2)
        except Exception:
            pass

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
            self.analyze_btn.setEnabled(True)
            self.cancel_btn.setEnabled(False)
            self.append_log('Background worker finished.')

    def on_progress(self, pct, processed, total, kept):
        # called from background thread
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


from PySide6.QtCore import QEvent
class _CallableEvent(QEvent):
    def __init__(self, callable_):
        super().__init__(QEvent.Type(QEvent.registerEventType()))
        self.callable = callable_


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
