# Security Policy — Audio Device Switcher

## Overview

Audio Device Switcher is a local, offline Windows desktop utility for switching the system default audio endpoint via a global hotkey. This document explains the application's security architecture, the technical rationale behind its privilege requirements, its file system footprint, and its complete absence of network activity — to establish that the application is not malware, spyware, adware, or any form of malicious software.

---

## Administrator Privilege Requirement

### Why Administrator Rights Are Mandatory

Audio Device Switcher requires and enforces elevation to `Administrator` token level at startup. This is not optional and cannot be bypassed. The requirement stems from three distinct technical dependencies in the Windows audio and scheduling subsystems, each of which individually mandates a high-integrity process token:

#### 1. IPolicyConfig COM Interface — Undocumented Audio Policy API

The core function of the application — changing the system default audio playback device — is performed through the `IPolicyConfig` COM interface (`IID: {f8679f50-850a-41cf-9c72-430f290290c8}`, CLSID: `{870af99c-171d-4f9e-af0d-e63df40c2bc9}`). This interface is an undocumented, internal Windows API that exposes `SetDefaultEndpoint`, which sets the default audio endpoint for all three role types simultaneously: `eConsole` (role 0), `eMultimedia` (role 1), and `eCommunications` (role 2).

`IPolicyConfig` is an internal Windows component that does not implement its own access control list (ACL) checks for standard user tokens. In practice, COM activation of this server under a medium-integrity (standard user) token fails silently or returns `E_ACCESSDENIED` at the `CoCreateInstance` call level. A high-integrity (Administrator) token is required for the `CoCreateInstance(POLICY_CONFIG_CLSID, IPolicyConfig, CLSCTX_ALL)` call to succeed and for subsequent `SetDefaultEndpoint` calls to be committed to the Windows audio session.

#### 2. Windows Task Scheduler (`schtasks`) — High-Privilege Task Registration

The "Add to Startup" feature registers a Windows Task Scheduler task (`AudioDeviceSwitcherStartup`) with the `/RL HIGHEST` flag, which instructs the scheduler to launch the task with the highest available privilege level at logon (`ONLOGON` trigger). This is necessary so that the application itself relaunches with an elevated token at startup — without which the `IPolicyConfig` calls described above would fail every session.

Registering a task with `/RL HIGHEST` via `schtasks /Create` requires an Administrator token. When the application is already running elevated (which it always is at runtime), it attempts the `schtasks` call directly. In the edge case where the call still requires separate elevation (e.g., UAC policy variations), the application generates a temporary `.bat` file in the user's `%TEMP%` directory, executes it via `ShellExecuteW` with the `runas` verb, and polls for a status sentinel file (`ads_status_<timestamp>.txt`) to determine success or failure. Both the `.bat` file and the status sentinel are deleted immediately after use — they are not persistent artifacts.

#### 3. Global Low-Level Keyboard Hook (`keyboard` library)

The application registers a process-wide global hotkey using the `keyboard` library, which internally installs a low-level keyboard hook (`WH_KEYBOARD_LL`) via `SetWindowsHookEx`. On Windows 10/11, low-level input hooks installed by processes running at medium integrity are subject to UIPI (User Interface Privilege Isolation) restrictions that can prevent the hook from receiving keystrokes when focus is held by an elevated-privilege application (e.g., a UAC dialog, Task Manager, or any process running as Administrator). Running the application at high integrity guarantees that the hook fires unconditionally regardless of the focused window's integrity level.

### Privilege Check at Launch

The `is_admin()` function calls `ctypes.windll.shell32.IsUserAnAdmin()` synchronously before any application code runs. If this returns `False`, the application displays a native Win32 `MessageBoxW` dialog and calls `sys.exit(1)` — no further code executes, no COM calls are made, and no files are created. The application **does not** silently self-elevate via `ShellExecuteW(runas)` at startup; the UAC prompt is never triggered by the application on behalf of the user unless the user explicitly clicks "Add to Startup" in the tray menu.

---

## Network Activity

**Audio Device Switcher makes zero network requests.**

The application contains no HTTP client, no socket, no DNS resolver, no telemetry agent, no analytics SDK, and no update checker. There are no calls to `urllib`, `requests`, `httpx`, `socket`, `ssl`, or any equivalent library. All data I/O is strictly local filesystem reads and writes (described below). Any network traffic attributed to the process by a firewall or network monitor is an artifact of the Windows COM/RPC subsystem (inter-process communication over named pipes and local RPC, which may appear as localhost traffic) and is not external communication.

---

## Python Standard Library & Third-Party Modules

The following modules are used. None communicate over the network.

| Module | Type | Purpose |
|---|---|---|
| `sys` | stdlib | Process control, frozen/script detection |
| `os` | stdlib | Filesystem path resolution |
| `json` | stdlib | Config file serialization/deserialization |
| `time` | stdlib | Timing delays for device state polling |
| `math` | stdlib | Pulse animation sine calculation |
| `ctypes` | stdlib | Win32 API calls (IsUserAnAdmin, ShellExecuteW, DwmSetWindowAttribute, MessageBoxW) |
| `threading` | stdlib | Background keyboard listener thread |
| `subprocess` | stdlib | `schtasks` query/create/delete calls |
| `comtypes` | third-party | COM interface binding for IPolicyConfig and IMMDeviceEnumerator |
| `keyboard` | third-party | Global low-level keyboard hook and hotkey registration |
| `pycaw` | third-party | Windows Core Audio API wrapper (device enumeration, volume query) |
| `PyQt6` | third-party | UI framework (widgets, animations, system tray, painter) |

---

## File System Footprint

The application reads and writes only to its own installation directory and the user's `%TEMP%` folder. It does not write to the registry (aside from what the Task Scheduler entry creates under `HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Schedule\TaskCache`), does not modify system files, and does not touch other users' profiles.

### Files Read at Startup

| File | Location | Description |
|---|---|---|
| `devices.json` | `<exe_dir>\devices.json` | User configuration: device list, display labels, category indices, custom icon references, and hotkey binding. Created on first save; absent on first launch. |
| `icon.ico` | `<exe_dir>\icon.ico` | Application icon for the system tray and window chrome. |

### Files Written at Runtime

| File | Location | Description |
|---|---|---|
| `devices.json` | `<exe_dir>\devices.json` | Overwritten on save with updated device/hotkey configuration. |
| `ads_task_<ms>.bat` | `%TEMP%\ads_task_<ms>.bat` | Temporary batch file for elevated `schtasks` operations. Deleted by the batch file itself upon completion via `del "%~f0"`. |
| `ads_status_<ms>.bat` | `%TEMP%\ads_status_<ms>.txt` | Temporary status sentinel written by the batch file to signal success or failure back to the main process. Deleted immediately after being read. |
| Custom icon copies | `<exe_dir>\icons\<filename>` | User-selected image files (PNG, JPG, etc.) copied into the `icons\` subdirectory when the user assigns a custom image icon to a device. The original file is not modified. |

### PyInstaller `_MEIPASS` Bundle Extraction

When distributed as a frozen executable (built with PyInstaller), the runtime extracts bundled resources into a temporary `_MEIPASS` directory managed entirely by PyInstaller. Audio Device Switcher copies exactly one file from `_MEIPASS` to the executable's directory at no point during runtime — `icon.ico` is bundled inside the executable and resolved at runtime via the `icon_path()` function, which first checks `<exe_dir>\icon.ico` and falls back to `sys._MEIPASS\icon.ico` if absent. No extraction or copying of `icon.ico` is performed by application code; PyInstaller handles bundle extraction transparently before `main()` is called.

---

## What the Application Does Not Do

- Does **not** read, write, or enumerate files outside its installation directory or `%TEMP%`
- Does **not** access the clipboard
- Does **not** log keystrokes — the `keyboard` library hook is used solely to detect the configured hotkey combination; no keystroke data is stored or transmitted
- Does **not** take screenshots or capture display content
- Does **not** access the camera or microphone
- Does **not** read browser history, cookies, or credentials
- Does **not** enumerate running processes beyond what Windows does implicitly via COM
- Does **not** inject code into other processes
- Does **not** modify or patch system binaries
- Does **not** communicate with any remote server, CDN, analytics endpoint, or update service

---

## Reporting a Vulnerability

If you discover a security issue in Audio Device Switcher, please open a GitHub issue or contact the maintainer directly. There is no formal bug bounty program. Please include a description of the issue, steps to reproduce, and any relevant environment details (Windows version, Python version if running from source).