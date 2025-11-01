# Design Notes for EPD Mate Filter

This document outlines the key design patterns and architectural decisions made in the `epd_mate.py` application.

## Core Architecture

The application follows a standard desktop GUI architecture with a clear separation between the user interface and the background processing logic.

### 1. GUI and Worker Thread Separation

- **Pattern:** Worker Thread
- **Implementation:** The main UI runs on the Qt event loop in the main thread. All time-consuming chess analysis is delegated to a background `AnalyzerThread` (a subclass of `threading.Thread`).
- **Rationale:** This is crucial for maintaining a responsive user interface. Without it, the GUI would freeze during the entire analysis process.

### 2. Thread-Safe GUI Updates

- **Pattern:** Event Posting / Asynchronous UI Updates
- **Implementation:** The `AnalyzerThread` cannot directly modify Qt widgets. Instead, it uses callback functions (`progress_callback`, `log_callback`, etc.) passed during its initialization. These callbacks wrap the UI update logic in a custom `_CallableEvent` and post it to the main window's event queue using `QApplication.instance().postEvent(self, _CallableEvent(upd))`. The `MainWindow.event()` method handles these events and executes the UI updates safely in the main thread.
- **Rationale:** This is the standard Qt-approved way to ensure thread safety when interacting with the GUI from other threads.

### 3. Graceful Task Cancellation

- **Pattern:** Cooperative Cancellation using an Event Flag
- **Implementation:** A `threading.Event` object (`stop_event`) is shared between the `MainWindow` and the `AnalyzerThread`. When the user clicks "Cancel," the main thread calls `stop_event.set()`. The worker thread periodically checks `self.stop_event.is_set()` within its main processing loop and exits cleanly if the event is set.
- **Rationale:** This allows the background task to shut down gracefully, closing files and the engine process properly, rather than being abruptly terminated.

### 4. Application Settings Persistence

- **Pattern:** Configuration Management
- **Implementation:** User settings, such as the last-used file paths, are saved to a simple JSON file (`epd_mate_settings.json`). The application loads these settings on startup and saves them when relevant paths are changed.
- **Rationale:** This improves user experience by remembering previous selections between sessions.

### 5. Compatibility Layer for Qt Bindings

- **Pattern:** Dynamic Module Loading / Adapter
- **Implementation:** The application uses a series of `try...except` blocks to attempt importing various Python Qt bindings (PySide6, PyQt6, PySide2, PyQt5). This allows the application to run without forcing the user to install a specific binding. It also handles minor API differences (e.g., the `@Slot` decorator name).
- **Rationale:** Increases the application's robustness and ease of setup in different Python environments.

### 6. Memory-Efficient File Processing

- **Pattern:** Streaming
- **Implementation:** When reading and analyzing the large EPD input file, the code iterates over it line by line (`for line in fin:`). It does not load the entire file into memory. The initial position count also reads the file in large chunks to avoid excessive memory usage.
- **Rationale:** This ensures the application can handle very large EPD files (millions of positions) without consuming a large amount of RAM.
