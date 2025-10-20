# Make Donations to support the developer:

## Monero XMR 
- 858KTnQzgVtcHmJodhmateWHg7Yxzivk4dxRAfofqdrbYzSnfeCqBrkD3H5ZtMG4YHCfqUG1wXuLi8yL9dw2GnEoNB1rsTX
- Please Send only Monero (XMR) on Monero Network to this address above . Sending other coins may result in permanent loss.

OR

## USD Coin (USDC)
- 3jwtyXg4dVAeGe2mPocUJb9WS8tSamMSdkhdzgsGpr2w
- Send only USD Coin (USDC) on Solana Network to this address. Sending other coins may result in permanent loss.

# All the Code here is made with love and care for chess, enjoy


# EPD Mate Filter

A small single-file Windows GUI app (PySide6 + python-chess) to filter EPD files for positions with forced mate within a user-configurable number of moves.

Features
- Load large EPD files (streamed, memory-friendly)
- Select a UCI engine (Stockfish recommended)
- Configure engine depth and threads
- Progress bar, ETA, and log output while analyzing
- Save filtered positions to a new EPD file
- Cancel analysis at any time
- Feature to add solve mate solution to FEN

Requirements
- Python 3.8+
- pip install python-chess PySide6
- A UCI engine binary (Stockfish) for Windows

Quick start

1. Install dependencies:

```powershell
pip install python-chess PySide6
```

2. Run the app:

```powershell
python epd_mate.py
```

3. In the app:
- Click "Open EPD" and choose your .epd file
- Click "Select Engine" and pick your Stockfish executable
- (Optional) adjust depth, threads and mate slider
- Click "Analyze" to start filtering; progress and log appear in the UI
- Click "Save As" to choose the output EPD file before starting

Troubleshooting

- If the GUI is non-responsive when starting analysis, ensure you are running a recent copy of `epd_mate.py` where the heavy analysis runs inside a background thread (the thread `AnalyzerThread.run()`).

- If you see repeated messages like:

```
Engine error on line N: 'PovScore' object has no attribute 'mate'
```

This indicates the engine analysis result uses a different score object (PovScore). The app includes robust extraction logic, but if you run into this, update `python-chess` to the latest version:

```powershell
pip install -U python-chess
```

Also ensure the engine you selected supports returning mate scores at the requested depth.

Persistence

The app can be extended to remember the last opened file and engine path. If you'd like, enable saving a small JSON `settings.json` in the app folder and load it on startup.

Contributing

- Open issues and PRs on GitHub.
- Keep changes small and test the UI on Windows.

License

MIT


- Please dont contact me for support, figure it out and love the new knowlege you gained.
