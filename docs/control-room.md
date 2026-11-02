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

## Views

One catalog drives every menu, in four groups. A view switch never reloads the page, fullscreen stays on.

| Group | Views |
|-------|-------|
| Workspaces | Writing room, Studio, Files |
| Status | Control room, Graphs, The night (replayed in thirty seconds), Brains, Threads |
| Maps | Observatory, Night city, Vault graph, Memory |
| System | System map, Components, Repos, Controls, Keys |

What some of them do:

- **Studio.** Everything the image, audio and 3D agents produce lands here. A 3D viewer for glb, fbx and obj with light and animation controls. Each file gets a level and a 0-5 rating. The 3D agent has a change queue per model: the owner writes what is wrong, the agent rebuilds, answers what it changed, and keeps the lesson for next time. Select and delete work on all three surfaces and go to a trash that can be undone.
- **Dig.** Semantic search over images, audio and 3D models, next to the memory search. A cosine floor on top of a z-score gate, so noise returns nothing instead of something.
- **Writing room.** The text lives in the vault. Read mode, dictation through the local speech-to-text daemon, read-aloud with a voice per character and tags with a range, cost per read shown before credits run out.
- **Observatory and Night city.** The system as a galaxy and as a city in the rain, with a timeline that replays the day. Both also run as screensavers on their own live channel, with a ceiling of L1 or L2 set from the control room.
- **System map.** Every running part, what it depends on and its state, including scheduled jobs and what lives outside the machine. It shows failures as they are.
- **Components.** Version and update need for runtimes, MCP servers, plugins and skills. It installs nothing.
- **Keys.** Add and rotate API keys from the web, only on the `local` channel.

---

## New code without a reload

The server announces the build it is running. When it changes, the client swaps code the next time the user is idle. A view that is busy (an upload, a recording, unsaved text) says so, and the swap waits. Views also keep their own data fresh. Nobody should ever have to press F5.

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
