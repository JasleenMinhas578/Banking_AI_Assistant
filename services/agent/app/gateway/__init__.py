"""The gateway: the one service the web app talks to.

    main.py    FastAPI app: calls, turns, PIN and code entry, audio in, speech out
    calls.py   one live call = an Agent + the bank session, kept in memory
    speech.py  speech-to-text (faster-whisper) and text-to-speech (Kokoro), both optional

It plays the part chat.py played in the terminal: it collects the PIN and the
one-time code itself and sends them straight to the bank, so no model sees them.
"""
