# Demo keystroke script — PULSE engineering session, 2026-08-10

Every keystroke, in order. Lines starting with `$` are typed exactly as shown, then Enter. Everything else is stage direction. Expected output fragments are what to glance for before speaking.

## 1.0 Before the meeting (T-15 min, off screen share)

Open Terminal, full screen, font ~18pt for the share.

```
$ cd /Users/Rob.Ford/orca/workspaces/pulse/dna-900-pulse-data-priority
$ clear
$ docker ps --format '{{.Names}}\t{{.Status}}'
```

Glance for three rows, all `Up`: `infra-ledger-relay-1`, `infra-ledger-postgres-1 (healthy)`, `infra-localstack-1 (healthy)`. The stack is still up from the 2026-08-09 rehearsal, so this should pass.

**Only if any row is missing:**

```
$ docker compose -f packages/ocean/infra/docker-compose.yml up -d --wait
```

Wait for `Healthy` lines (~1–2 min since images are cached). Then:

```
$ clear
```

Leave the terminal on this empty prompt. Open browser tabs in this order (they mirror the talk): the repo, the v2.0 release, the v1.5 release. Do not open Linear on the shared screen.

## 2.0 Live — the main demo (one command, four beats)

When you reach the demo section of the talk:

```
$ uv run python scripts/demo/demo1_ledger_core.py --skip-compose-up
```

`--skip-compose-up` matters: the stack is already running, and it cuts the Docker noise so output starts at the banner. The script prints four numbered assertions in ~30 seconds. Narrate each as it lands:

- After `[1/4] legal command commits and lands on the queue` — point at the SQS URL in the output: "one API call, and it is already on the AWS transport we run today."
- After `[2/4] illegal command rejects with catalog reason + version` — pause here. Read the rejection line aloud, including `(catalog 1.0.0)`. This is the governance beat.
- After `[3/4] replay returns the original event id` — "same idempotency key twice, one event stored."
- After `[4/4] independent fold equals current_state` — the closer: "we just recomputed state from raw events, from scratch, and it matched. Anyone here can re-derive the number."

Final line to point at: `=== Demo 1: all four assertions passed ===` — "and this script exits nonzero if any of those had failed."

## 3.0 Reserve demos (run only if the room asks)

Both are offline — no Docker, no network, safe even if the stack dies.

**"What about humans / the ops board?"**

```
$ uv run python scripts/demo/demo2_kanban_drag.py
```

Narrate: an HMAC-signed synthetic drag becomes an attributed command; the invalid drag is rejected and the reason is written back onto the card.

**"How do you avoid merging two different patients?"**

```
$ uv run python scripts/demo/demo2_identity_matcher.py
```

Narrate: deterministic matching, and a genuine conflict routes to quarantine — the system never auto-merges ambiguous humans.

## 4.0 If the live run breaks

Do not debug on screen. Say: "this ran green last night — let me show you the receipt," and open the rehearsal output:

```
$ less /private/tmp/claude-502/-Users-Rob-Ford-orca-workspaces-pulse-dna-900-pulse-data-priority/7ee8acc9-ed6b-4e8e-865c-a33dd028f8d2/tasks/b4733mgtm.output
```

Then `G` (jump to end) to land on the four assertions and the pass banner. `q` to quit. Caution: that path is a session temp file — copy it somewhere stable before the meeting:

```
$ cp /private/tmp/claude-502/-Users-Rob-Ford-orca-workspaces-pulse-dna-900-pulse-data-priority/7ee8acc9-ed6b-4e8e-865c-a33dd028f8d2/tasks/b4733mgtm.output ~/Desktop/demo1-rehearsal-2026-08-09.log
```

## 5.0 After the meeting

Leave the stack running if a follow-up hands-on session is likely. Otherwise:

```
$ docker compose -f packages/ocean/infra/docker-compose.yml down
```
