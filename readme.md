# 🔊 Audio Device Switcher

## 😤 Tired of Windows' BS?

Tired of clicking through five different menus just to switch from
your headset to your speakers (and back again, and again)?

**Not anymore.** This is the fix for that Windows slop — switch your
audio output device instantly with a single hotkey, and you're in the
right place. 🎧✨

## ⭐ Features

- 🔁 Switch your default audio output device instantly with a global
  hotkey (default `Ctrl+]`)
- 🏷️ Custom labels and icons/emojis per device, so you actually know
  which is which at a glance
- 🖱️ Tray icon for quick access to edit your devices, toggle startup,
  or close the app
- 🚀 Optional "Launch at Startup" toggle
- 🔒 Runs entirely locally — no network access, no telemetry (see
  [security.md](security.md))

## ✅ Requirements

- Windows 10 (version 1809 or later) or Windows 11 — the audio
  endpoint–switching API this app relies on requires that minimum
  build
- Administrator rights (needed for the global hotkey and the startup
  toggle — see [security.md](security.md) for why)

## 📥 Getting the Source

**Option 1 — git clone:**
```bash
git clone https://github.com/Anonymi69/audio-device-switcher-utility.git
```

**Option 2 — don't want to deal with git or GitHub's "Code" button?**
Grab the zipped source straight from the repo's
[**Releases**](https://github.com/Anonymi69/audio-device-switcher-utility/releases/)
page instead — it's just a pre-packaged copy of the full source, no fuss.

> ⚠️ Note: there's no pre-built `.exe` release. Random pre-built
> binaries are a classic way malware spreads, so to keep this
> trustworthy, you build it yourself from source (literally one
> double-click — see below 👇). Full reasoning in
> [security.md](security.md).

## 🧪 Running It as a Raw Script (for testing/development)

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Run it directly:
   ```bash
   python main.py
   ```
   Run this from an elevated (admin) terminal, or the app will prompt
   you to relaunch with admin rights — without them, the hotkey and
   startup features won't work.

## 🔨 Building It Yourself

`build.bat` handles everything — you don't need to install
dependencies separately for this path (it does that for you).

1. Make sure `icon.ico` is present in the project root before
   building. If it's missing, the build still succeeds but produces
   an exe with no custom icon.
2. From the project root, double-click (or run):
   ```bash
   build.bat
   ```
   This will:
   - Install/upgrade dependencies from `requirements.txt`
   - Clean any previous `build/`, `dist/`, and `.spec` artifacts
   - Build a single-file, no-console executable with PyInstaller
   - Output it as `dist\Audio Device Switcher.exe`
   - Open the `dist` folder when done
3. Test it by:
   - Running `Audio Device Switcher.exe` **as administrator**
     (right-click → "Run as administrator"), **or**
   - Launching it from an already-elevated terminal/command prompt

If it's run without admin rights, the app will not work at all —
this is expected, not a bug. 🙂

## 💾 Configuration

Your device list, labels, and hotkey are saved locally to
`devices.json` next to the executable. Nothing is sent anywhere — see
[security.md](security.md) for full details on data handling.

## ❓ FAQ

**How do I add another device later?**
Right-click the tray icon → **Edit** → add the device(s) you want →
hit **Save**. Done. 🎉

**How do I change my hotkey later?**
Same place — right-click the tray icon → **Edit**, where you can set
a new hotkey, then **Save**.

**Is this app CPU heavy?**
Nope, it's very lightweight — typically under 1% CPU usage and no
more than ~50MB of memory. 🪶

**Is this a virus? Is this app safe?**
This is not a virus. We don't distribute any executables — you build
it yourself from the source in this repo using `build.bat`. Since
there's no binary floating around for anything to be hidden in, you
can verify it however you like: read the source yourself, or paste it
into any AI chatbot and ask it to review what the code actually does.
Because you control the build end-to-end, the risk of a hidden virus
is effectively zero. See [security.md](security.md) for a full
breakdown of what the app does and doesn't touch on your system.

**Is this free?**
Yes, 100% free. No premium tier, no paywalled features, no catch. 💸❌

**Does it contain ads?**
Nope. This app is totally ad-free, and there are no quirks or hidden
catches anywhere in it. 🚫📢

## 🛡️ Support

We genuinely welcome security analysts, researchers, or anyone with
the skills to manually go through the entire codebase line by line —
not just skim it. Check for anything obfuscated, hidden, or
suspicious that could indicate malicious behavior. The source is
right here in this repo, nothing is hidden, and there's no compiled
binary distributed anywhere to muddy that inspection — what you build
is exactly what you read.

If you do go through it and find anything concerning (or even just
have questions about why something is implemented a certain way),
please open an issue or reach out — we'd genuinely like to know.

## ⭐ Like It?

If this saved you a few clicks (and a little bit of your sanity), a
star on the repo goes a long way 🙌 — costs nothing, helps others find
it.
