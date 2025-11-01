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

## Features
- Load large EPD files (streamed, memory-friendly)
- Select a UCI engine (Stockfish recommended)
- Configure engine depth and threads
- Progress bar, ETA, and log output while analyzing
- Save filtered positions to a new EPD file
- **Generate a JSON file of mate puzzles** for use in other applications
- Cancel analysis at any time
- Option to add the full mate solution to the output EPD file
- Option to fix the move order in the JSON output so the winning side is to move

## Requirements
- Python 3.8+
- `pip install python-chess PySide6`
- A UCI engine binary (e.g., Stockfish) for Windows

## Quick start

1.  **Install dependencies:**
    ```powershell
    pip install python-chess PySide6
    ```

2.  **Run the app:**
    ```powershell
    python epd_mate.py
    ```

3.  **In the app:**
    - Click **"Open EPD"** and choose your `.epd` file. Default output paths for EPD and JSON files will be suggested automatically.
    - Click **"Select Engine"** and pick your Stockfish executable.
    - (Optional) Adjust the **Engine Settings** (Depth, Threads) and the **Mate Finder** slider.
    - (Optional) Choose different output paths for the EPD and JSON files by clicking **"Save As"** or **"Save JSON As"**.
    - (Optional) Toggle the checkboxes to control whether the mate solution is added to the EPD or if the move order is fixed in the JSON output.
    - Click **"Analyze"** to start filtering. Progress and logs will appear in the UI.

## JSON Output Format

The generated JSON file contains a list of puzzles in the following format, suitable for puzzle trainers or databases:

```json
{
  "theme": "Mates",
  "pattern": "Mates",
  "puzzles": [
    {
      "fen": "3qr2k/3p2pp/7N/3Q2b1/8/8/5PP1/5RK1 w - - 0 1",
      "solution": [
        "d5g8",
        "e8g8",
        "h6f7#"
      ],
      "moves_to_mate": 3,
      "elo": 1200,
      "solved": 0,
      "failed": 0
    }
  ]
}
```

## Troubleshooting

- If the GUI is non-responsive during analysis, ensure you are running a recent version of the script where analysis runs in a background thread.
- If you see engine errors related to score types, try updating your `python-chess` library:
  ```powershell
  pip install -U python-chess
  ```

## Persistence

The app automatically saves your last-used file and engine paths in `epd_mate_settings.json` and reloads them on startup.

## License

MIT

- Please dont contact me for support, figure it out and love the new knowlege you gained.
