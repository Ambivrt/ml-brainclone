# Control Room — the web app

A local web app that shows the whole system at once and lets you act on it: what is waiting for you, what broke, what the bus is saying, which sessions run, what the night did. It runs on the same machine as the daemons and reads their state directly. Nothing is stored in a cloud.

It is an application, not a page. Every view remembers how you left it, on every device.

---

## Channels

One process, several listeners. Each listener is a **channel** with its own privacy ceiling.

| Channel | Listens on | Reached from | Default ceiling |
|---------|------------|--------------|-----------------|
| `local` | `127.0.0.1:8801` | this machine, always | L4 |
| `tunnel` | `127.0.0.1:8800` | the phone, through a tunnel behind an access policy | L2 |
| `dev`, `dev-local` | own ports | a development copy with its own data directory | L2 / L4 |

The tunnel listener only opens when the access policy in front of it **verifies** at start (see `scripts/stack-start.ps1`, `Invoke-AccessGate`). A policy that does not verify leaves the app local, never open on the internet. A flaky network at start is retried, because a restart triggered from the phone ends exactly there, and one failed call would otherwise lock the phone out.

Every request is checked for host, origin and CSRF centrally. A route cannot forget it.

---

## Privacy per channel

The ceiling is per channel, chosen by you, held by the server (`privacy.json` next to the app's config). There is no time lock and no confirmation to raise it. Lowering it takes effect for every open client on that channel at once.

The server **projects** everything for the receiving channel's level: the snapshot, every delta on the event stream, chat turns. A client at L2 never receives L3 text and hides it; it never gets it. A message queued before the ceiling changed is dropped instead of delivered, so an L4 answer can never arrive after a drop to L1.

"Hide" sets L1 and empties the screen. It is the button for a shared screen.

Ceilings are deliberately separate per channel: setting L4 at the desk does not put L4 on the phone in the street. Whether to link them is a decision for the owner, not a default.

---

## Live data

- **Snapshot + stream.** The page loads one snapshot, then follows a server-sent event stream: bus events, daemon state, sessions, what is waiting, chat. After a reconnect it gets deltas and the missed bus events in id order, never one twice.
- **One stream per browser.** Tabs elect a leader with Web Locks; the leader holds the stream and forwards events to the others over `BroadcastChannel`. A frozen leader is detected and replaced.
- **Last known state.** When the app is down the page shows the last snapshot, stored locally, capped at L2.
- **Fixture mode.** `?fixture` runs the whole server inside the browser from JSON fixtures: every view, every action, no network. `&level=3`, `&channel=local` pick the starting state. It is how the UI is built and tested without touching real data.

---

## Settings that follow you

Every choice you make in the UI is stored on the server and pushed live to every other open client, on every channel: a filter in the media studio, the timeline's view and speed, folded sections, the chat's selected agent, the tab you left a panel on, the theme. Open the studio on the phone and it opens where you left it at the desk.

```
GET  /api/prefs          -> {"prefs": {key: value}, "levels": {key: level}}
POST /api/prefs          {"key", "value" (null deletes), "level"}
stream event "prefs"     {"key", "value", "level"}
```

Client side, one API in the shared live client:

```js
LarryLive.prefs.get('studio.yta', 'barry')
LarryLive.prefs.set('studio.folder.barry', {sub: 'portraits'}, {level: currentLevel})
LarryLive.prefs.on('kr.tl.view', v => setView(v))
```

Rules that keep it safe:

- **Every entry carries a level.** A value that says something about content (a folder name in a filter) gets the level it was chosen at; a channel sees only entries at or below its ceiling. Type, order and other plain choices are L1 and follow you everywhere.
- **The level is decided at the click, not at the save.** If the ceiling drops between the click and the write, the write is refused (403), never clamped down. Clamping would store an L4 folder name as L2. Pending writes above a lowered ceiling are dropped.
- **Free text is never stored.** Searches, tags and selected nodes can be L3 and stay in the page.
- **Bounded.** Short keys, values up to 2 kB of JSON, a few hundred keys. Lists of item ids are pruned to items that still exist before they are saved.
- **Migration only on success.** Old `localStorage` values move to the server once and are removed locally only after the server confirmed the write.
- **Offline mirror.** Values at L1-L2 are mirrored locally so the phone still opens in the right mode without a network. The server stays the truth; the mirror is cleared with the last-known state.

`localStorage` alone for settings is a 2010 web page. The only things allowed to live there are the offline mirror, the last-known snapshot and an outbox of messages typed while offline.

---

## Switching parts off

The control room can switch a part of the stack off (`parts-off.json`) or rest it during game mode (`game-mode.json`). The start script and the watchdog both read these files, so a part you switched off stays off through a watchdog cycle and a reboot. Without that, the watchdog restarts within a minute what you just turned off.

---

## Read signal

Opening an auto-generated report in the file viewer logs a read (`{path, at, via}`, never content) when the viewer is the owner on `local` or `tunnel`. The information lifecycle (see `docs/lifecycle.md`) uses it to tell read from unread. Frontmatter is never touched for it.

---

## See also

- `docs/privacy-architecture.md` — levels, taint
- `docs/lifecycle.md` — what leaves the inbox and when
- `scripts/stack-start.ps1` — the access gate, `-Only Web` to restart just the app
