# ADR-006: The web app has no build step

**Status:** accepted · **Date:** 2026-10-31

## Context
The design named React + Vite. The app has one screen: pick a customer, talk, enter a PIN on a keypad, see what decided each turn.

## Decision
`services/web` is plain HTML, CSS and JavaScript served by the gateway itself at `make serve`. It talks only to `/api`. Voice uses the browser's microphone (MediaRecorder) for Whisper on the server and plays Kokoro audio back; without the voice extras it falls back to typing and the browser's own speech synthesis, and says so.

## Consequences
- `make serve` is the whole front-end setup: no Node, no bundle, nothing to keep in sync with the API.
- No component framework, so the app stays small by necessity; a bigger product would reach for one.
