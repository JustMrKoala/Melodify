# Melodify

A Spotify-inspired offline music player for Windows, macOS and Linux. Search for any song, download it as an MP3, and play it locally without a subscription or internet connection after the initial download.

---

## What it does

Melodify lets you build a personal music library by searching YouTube, downloading audio, and playing everything back through a clean dark-themed desktop interface. It remembers what you have listened to, organises songs into playlists, and takes care of storage automatically over time.

### Core features

**Search and download**
Type any song name or artist into the search bar. Results come back from YouTube via yt-dlp. Hit the download button on any result and the audio is saved to your computer as an MP3. A progress bar inside the card shows download and conversion status in real time. Once the download finishes the button turns into a play button instantly, no refresh needed.

**Playback**
Songs play through pygame, which handles audio directly without needing any external media player. The bottom player bar shows the current song title and artist, a draggable seek bar you can click or drag to jump to any position, a time counter, and a volume slider. Pause, resume, skip forward, skip back, shuffle and repeat are all available.

**Playlists**
Every downloaded song is added to the Default playlist automatically. You can create as many custom playlists as you want using the sidebar. Songs can be added to multiple playlists at once through the inline dropdown that appears when you click the add button on a song card. A dedicated Liked Songs playlist is always available for quick access to favourites.

**Library management**
The Library view shows all downloaded songs with total storage used and a count of compressed files. Each song card has a delete button that removes the file from disk and cleans it out of all playlists. On startup the app checks that every file in the library still exists on disk and quietly removes any entries whose files are missing, so the library never shows ghost songs you cannot play.

**Auto-compression**
Songs that have not been played in a configurable number of days (default 30) are automatically compressed from 192kbps stereo down to 64kbps mono, saving roughly 70 percent of disk space. Compression runs in the background and a badge on the card shows when a file has been compressed. You can also trigger compression manually from the sidebar.

**Accent colour customisation**
Open Settings and go to the Appearance tab to change the accent colour used throughout the app. Ten preset swatches are available (Spotify Green, Electric Blue, Neon Pink, Tangerine, Purple, Amber, Cyan, Red, Emerald, Cherry) or you can type any hex code. The logo, player controls, seek bar, buttons and highlights all update immediately. The chosen colour is saved and restored on next launch.

**Autoplay and shuffle**
When you play a song from the Library or from a playlist the entire list becomes the autoplay context. The skip buttons navigate through that list in order. Shuffle mode randomises the order and cycles through all songs before repeating. Repeat mode loops the current song. Playlists have Play All and Shuffle buttons in the header for one-click playback.

**Recommendations**
The home screen shows recently played songs and suggests artists to search for based on your most-played music.

---

## Requirements

Install the Python dependencies before running:

```
pip install customtkinter yt-dlp Pillow requests pygame pytubefix
```

ffmpeg is optional but recommended for better audio quality and compression. If it is not installed the app will offer to install it automatically using Scoop (Windows), Homebrew (macOS) or apt/snap (Linux).

---

## Running from source

```
python melodify.py
```

---

## Packaging with PyInstaller

Melodify can be packaged into a standalone executable using PyInstaller so users do not need Python installed:

```
pip install pyinstaller
pyinstaller --onefile --windowed melodify.py
```

The resulting executable will be in the `dist` folder.

### Antivirus false positives

**If you download a pre-built Melodify executable, your antivirus may flag it as suspicious or malicious. This is a known false positive.**

PyInstaller works by bundling the Python interpreter, all dependencies and the application code into a single executable file. Many antivirus engines flag this packaging method because the same technique is used by some malware. The executable itself contains nothing harmful.

If you are concerned, the safest option is to run Melodify directly from the source file (`melodify.py`) using your own Python installation rather than using a pre-built binary. The full source code is available and can be reviewed before running.

You can verify a downloaded executable by checking its hash against the one published by the author, or by scanning it on [VirusTotal](https://www.virustotal.com) and reading the individual engine results. Detections from heuristic engines with names like "Trojan.Generic" or "Suspicious.Cloud" in the context of a PyInstaller binary are almost always false positives.

---

## Data storage

All app data is stored in a folder called `.melodify` in your home directory:

- `music/` contains downloaded MP3 files
- `thumbnails/` contains cached album art
- `tmp/` is used temporarily during downloads
- `data.json` stores song metadata, playlists, play history and settings

To fully uninstall Melodify, delete the `.melodify` folder and remove the script.

---

## Settings

| Setting | Description |
|---|---|
| Download folder | Where MP3 files are saved (default: `~/.melodify/music`) |
| Compress after (days) | How many days without playback before a song is compressed |
| Accent colour | The highlight colour used throughout the interface |
