"""Xenticorp Ripnamer - rename MakeMKV / MP4 TV rips into Jellyfin episode names using TMDb.

Package layout
    config.py   settings file, baked-in key, bundled resources
    media.py    video discovery + native MKV/MP4 duration readers
    tmdb.py     TMDb client (retries, caching) + episode-group helpers
    planner.py  turns files + episodes into a rename plan (pure logic)
    mover.py    executes a plan with progress/cancel, writes undo logs, undoes
    discs.py    disc labels -> show/season/disc, show name -> one TMDb show (headless)
    cli.py      headless plan / apply commands: python3 -m ripnamer_app.cli
    ui/         Tkinter front end (theme + app + settings dialog)
"""

APP = "RipNamer"
VERSION = "3.2.0"
