# Telegram Channel TTS Reader

Reads new posts from one or more Telegram channels aloud, in real time, on a
computer you leave running. Comes with a local web portal for logging in,
picking channels, and assigning voices — plus a headless CLI script for
systemd/no-browser use.

## How it works

- Logs in as **your own Telegram account** (not a bot) using the Client API,
  so it can watch any channel you're subscribed to — not just ones you admin.
- Listens for new messages via an event handler (push-based, no polling).
- Speaks each message using your OS's local text-to-speech voices — a
  different voice per channel when you're listening to more than one.

## Setup

1. **Get API credentials** (one-time, free):
   - Go to https://my.telegram.org/apps
   - Log in with your phone number
   - Create an app (any name/platform works — it's just for API access)
   - Copy the `api_id` and `api_hash`

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
   On Linux, also install a speech engine:
   ```bash
   sudo apt install espeak
   ```

3. **Configure** — copy `.env.example` to `.env` and fill in `API_ID` /
   `API_HASH` from step 1. That's all the portal needs; `.env` is gitignored
   and never committed.

## The web portal (recommended)

Quickest path — one script handles setup and launch:
```bash
./run.sh
```
It creates a venv, installs dependencies, and (on first run) creates `.env`
from the template and asks you to fill in `API_ID`/`API_HASH`, then re-run.
After that it starts the portal and opens it in your browser automatically.

Or run it by hand if you'd rather see each step (same prerequisites as
above — dependencies installed, `.env` filled in):
```bash
python app.py
```
Open **http://127.0.0.1:8765**. First run walks you through logging in
(phone number → the code Telegram sends you → your two-step password, if
you have one set) — same as adding a new device. From there:

- **Tune in a channel** to browse everything your account is a member of
  and add it to your list.
- Each channel gets an **enable switch**, a **voice** picker (auto-assigned,
  or pick one and hit **Preview** to hear it), and a **mute** toggle to
  silence it temporarily without removing it.
- **Speech rate** and **volume** sliders tune playback.
- **Forwarding targets**: add one or more other channels/groups (via the
  same "Tune in" picker), then flip the **Forward** toggle on any listened
  channel to repost its new messages there too — as a fresh message, not a
  native Telegram forward. Each target can be enabled/disabled independently.
- **Start listening** goes live; a **transmission log** on the right shows
  what's been read aloud as it happens, including how many forward targets
  each message reached.
- Changing channels/voices while already listening shows a **Restart to
  apply** prompt — Telegram's event subscription is fixed per-connection,
  so picking up a channel-list change means restarting the listener (your
  login session is untouched).

It binds to `127.0.0.1` only — reachable from this machine (Mac, Linux,
Chromebook/Crostini, wherever you run it), not your network. There's no
separate portal login: the person who can reach `127.0.0.1` on this machine
*is* the person allowed in, same as any other localhost dev tool.

Settings (channels, voices, mute, forward flags/targets, speech rate,
volume) are stored in `config.json`, a plain JSON file next to the scripts —
no database. It's gitignored, same as `.env`; `config.json.example` shows
its shape.

## Headless / CLI script

For a machine with no browser access (e.g. a systemd service), use the
original script instead — same underlying logic, configured via `.env`:

```bash
python telegram_tts_reader.py
```

Add to `.env`:
- `CHANNEL` — the channel's username (from its `t.me/xxxx` link, just the
  `xxxx` part), or a numeric ID for a private channel (see below). To
  listen to several channels at once, list them separated by commas
  (e.g. `CHANNEL=durov,-100123456789`) — each one automatically gets its
  own TTS voice, see `CHANNEL_VOICES` in `.env.example` to pick specific
  voices instead.
- Optional tuning: `SPEECH_RATE` (words per minute, default 175) and
  `ANNOUNCE_SENDER` (prefix messages with the channel name — automatic
  whenever `CHANNEL` lists more than one channel, regardless of this flag).

First run asks for your phone number and login code, same as the portal.
Either entry point creates/reuses the same `tts_reader_session.session`
file, so logging in once via the portal means the CLI script won't ask
again, and vice versa.

### Finding a private channel's ID

Public channels just use their `t.me/xxxx` username. For a private channel
with no public link, run:
```bash
python list_my_channels.py
```
This prints every channel/group your account is in, with its numeric ID.
Use that number as `CHANNEL` (or find it in the portal's "Tune in a
channel" list instead).

## Running on other platforms

Both the portal and the CLI script work unmodified on **Windows**, **Linux**,
**macOS**, and **Android via Termux** — `pip install -r requirements.txt`,
then a `.env` file next to the scripts. See "running it continuously" below
for keeping the CLI script alive in the background on each platform.

## Running the CLI script continuously

For a machine you leave on, install the headless script as a background
service so it survives logouts and restarts automatically if it crashes.
(The portal is meant to be started when you're at the machine to use it —
if you want it always-on too, the same approaches below apply, just point
them at `app.py` instead.)

**Linux (systemd):**
```bash
# edit telegram-tts-reader.service first: replace YOUR_USERNAME and the paths
cp telegram-tts-reader.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now telegram-tts-reader.service
```
Check it's running: `systemctl --user status telegram-tts-reader.service`
View logs: `journalctl --user -u telegram-tts-reader.service -f`

**macOS:** wrap it in a `launchd` plist, or simply run it inside a
`tmux`/`screen` session so it survives you closing the terminal.

**Windows:** add it as a Scheduled Task set to run at login, or use
[NSSM](https://nssm.cc/) to install it as a proper Windows service.

## Notes

- Messages queue and play one after another, so a burst of posts won't talk
  over each other.
- Pure media posts with no caption are silently skipped (nothing to read).
- Your `tts_reader_session.session` file is a live login to your Telegram
  account — keep it as private as a password; don't commit it to a public repo.
