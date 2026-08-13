# Orca Cloud Host on Duplo DEV01-BROOK — Implementation Spec

**Date:** 2026-08-13 · **Owner:** Ford · **Status:** Live. Runtime paired, Claude authenticated

## Operating it

```bash
# Connect (starts the host if idle-stop powered it down, then forwards 7331)
scripts/orca-host/tunnel.sh

# Drive the remote runtime
orca status --environment dev01-brook
orca repo list --environment dev01-brook

# Interactive shell on the host
aws --profile duplo-dev01 ssm start-session --target i-0e0d5170c240c9b9d

# Cost control by hand
duploctl --host "$DUPLO_HOST" --tenant dev01-brook --interactive hosts stop orca
```

The tunnel must be running for the desktop to reach the runtime. The host itself does
not care — it keeps working while the laptop sleeps, which is the point.

Session Manager terminates a port-forward on its own inactivity timeout, and sleep or a
network change drops it too. `tunnel.sh` supervises the session and reconnects rather
than exiting, re-checking the host each time in case idle-stop powered it down while
disconnected. Verified by killing a live session and watching it rebuild.

**If the desktop reports the environment Offline**, suspect the tunnel before the host.
Diagnose in order: listener on 7331, supervisor process, host state, runtime. A dead
tunnel means no connected client, so with no agent running the host idle-stops correctly
and the desktop goes Offline as a second-order effect. `tunnel.sh` restarts a stopped
host, so recovery is one command.

Two fixes came out of hitting exactly that: `--bg` now uses `nohup` plus `disown`,
because a bare `&` left the supervisor a child of the invoking shell and it died with it,
and the stopped-host restart mints its token with `duplo-jit` rather than
`duploctl --interactive`, which blocks without a TTY and so fails under launchd, a
background job, or an agent harness.

Auth is the Claude subscription login, made once inside the host and stored at
`/home/ubuntu/.claude/.credentials.json`. If those OAuth credentials ever expire while
you are away, the fallback is `Environment=ANTHROPIC_API_KEY=...` in
`orca-serve.service`, which never needs a terminal but bills as API usage.

### Git access

`pulse` is cloned at `/home/ubuntu/workspace/pulse` and registered with the remote
runtime. Access is a **deploy key**, not a token: an ed25519 keypair generated on the
host, whose private half has never left it, with the public half attached to
`robford-brookai/pulse` as key `160162334` with write access.

Blast radius is exactly one repository. GitHub confirms the scope on authentication —
it answers `Hi robford-brookai/pulse!` rather than naming your account. Nothing expires,
which is what an unattended host needs. Adding a second repository means either a second
key or a move to a fine-grained token.

The `github.com` host key was pinned after verifying its fingerprint
(`SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU`) against GitHub's published value,
and `StrictHostKeyChecking` is on.

### Workspace trust — recurring gotcha

Claude Code trusts projects by absolute path. A **new worktree starts untrusted, and an
untrusted workspace has its `permissions.allow` entries silently ignored.** Unattended,
that shows up as an agent stalling on a prompt nobody answers.

Run `scripts/orca-host/trust-workspaces.sh` on the host after creating worktrees.

### Verified end to end

A worktree was created on the host, Claude ran inside it and returned the expected
string with exit 0, the trust fix was confirmed to silence the warning, and the test
worktree was removed.


## 0. Build log — what changed during execution

Four things in this spec turned out differently once the host existed.

| Predicted | Actual | Fix |
|---|---|---|
| SSM available to the tenant role | `ssm:SendCommand` and `ssm:StartSession` both denied. Only reads were granted | Added inline policy `OrcaHostSSMAccess` to `duploservices-dev01-brook`, scoped to `TENANT_NAME=dev01-brook`. Applied with `duplomaster` credentials |
| `.deb` install is self-contained | Installed cleanly, then failed at exec on `libgbm.so.1`. The package under-declares its Electron dependencies | Added eight runtime libraries to `install-orca.sh` |
| `orca-ide serve` support unconfirmed | Confirmed working, and it self-installs its CLI to `~/.local/bin` | None needed |
| Duplo host spec unknown | Modelled on `dashboard-host`, the tenant's only non-EKS native host | `AgentPlatform: 0`, Ubuntu 22.04 image rather than its Amazon Linux one |

### 0.1 Rebuild for performance and cost

The first host was rebuilt after discovering it ran `t3.xlarge` in `unlimited` credit
mode — the worst configuration for sustained agent work. A burstable instance with a
40% baseline, billed a surcharge to exceed it, costs near-`m7i` money for older cores.

Moving to `m7i.2xlarge` and adding idle auto-stop gives twice the cores, twice the
memory, faster silicon, and a lower monthly bill, because the host stops paying for the
16 hours a day nobody uses it.

| | Before | After |
|---|---|---|
| Instance | t3.xlarge, burstable | m7i.2xlarge, sustained |
| Cores / memory | 4 vCPU / 16 GB | 8 vCPU / 30 GB |
| Disk | 3000 IOPS, 125 MB/s (gp3 floor) | 6000 IOPS, 250 MB/s |
| Idle behaviour | runs forever | stops after 2h quiet |
| Compute cost | ~$121/mo at 24/7 | ~$98/mo at 8h/day |

Idle detection treats a running `claude` or `codex` process as activity, not just a
connected client. Unattended overnight work is the reason this host exists, so an active
agent must never read as idle. Verified: a quiet host accumulates (10m, 20m), a running
agent resets the counter to zero, and a 15-minute uptime floor prevents boot loops.

Live resource: `i-0e0d5170c240c9b9d` at `10.221.9.3`, `orca-serve` and
`orca-idle-stop.timer` both enabled and active, Claude Code 2.1.231 installed and not
yet authenticated.

## TL;DR

You asked for an Orca cloud virtual machine (VM) on the Duplo non-production tenant
DEV01-BROOK so Claude can keep working while your MacBook sleeps. The per-workspace
environment recipe path the Orca skill describes is **not buildable in this tenant** —
the tenant role cannot create machine images, which kills both snapshot phases the
recipe depends on.

The recommendation is a **single persistent Duplo host** running `orca serve`, with
Claude authenticated once inside it. It sidesteps both blockers, matches what you
actually asked for, and costs roughly 130 dollars a month left running.

Your Mac reaches it through an AWS Systems Manager (SSM) port-forward, so nothing new
is exposed inbound and no new secret is introduced.

## 1. What the investigation found

### 1.1 The tenant role is read-only for compute

Five mutating EC2 calls were tested against the `duploservices-dev01-brook` role on
2026-08-13. All five were refused.

| Action | Result |
|---|---|
| `ec2:RunInstances` | UnauthorizedOperation |
| `ec2:StopInstances` | UnauthorizedOperation |
| `ec2:TerminateInstances` | UnauthorizedOperation |
| `ec2:CreateTags` | UnauthorizedOperation |
| `ec2:CreateImage` | UnauthorizedOperation |

Duplo owns compute mutation through its own control plane. Direct `aws ec2` calls work
for reads only.

### 1.2 Machine image creation has no path at all

- `ec2:CreateImage` is denied to the tenant role, per 1.1.
- `duploctl` exposes exactly six host verbs — `find`, `apply`, `delete`, `stop`,
  `start`, `reboot`. None creates an image.
- The tenant owns zero custom images today (`describe-images --owners self` returns 0).

The Orca recipe architecture is base snapshot, then authentication snapshot, then fast
per-workspace boots. Without image creation both snapshot phases are impossible, and
every workspace creation would demand a fresh interactive Claude login. That is not a
workable autonomous setup.

### 1.3 Orca publishes Linux builds

Release v1.4.180 ships `orca-ide_1.4.180_amd64.deb`, an equivalent RPM, and an
AppImage. Only the Homebrew cask is macOS-only. The Linux binary is named `orca-ide`,
matching the skill's instruction to never run bare `orca` on Linux, where it resolves
to the GNOME screen reader.

This removes the source build entirely. No `pnpm install`, no electron-vite step.

### 1.4 The network is closed, and SSM is already the way in

Every workload in the tenant runs in a private subnet with no public address. The one
public IP in the virtual private cloud belongs to an OpenVPN appliance. Meanwhile SSM
reports 11 instances online, and the `duploservices-dev01-brook` instance profile is
among the managed set.

SSM gives you a control channel and a port-forward with no inbound exposure, no SSH
keys, and no bastion.

## 2. Architecture

One persistent Duplo host, created through the Duplo application programming interface
(API), running `orca serve` under systemd so it survives reboots. Worktrees live inside
that remote runtime as ordinary Orca worktrees rather than as separate VMs.

Your Mac pairs to it over an SSM port-forward. When the Mac sleeps, the host keeps
running and any dispatched agent work continues. On wake you restart the forward and
reattach.

One honest limit: the Mac remains the control plane for *starting* new work. Asleep,
you cannot launch something new. Anything already running continues untouched.

### 2.1 Rejected alternatives

| Option | Why not |
|---|---|
| Per-workspace recipe (the skill's default) | Blocked by 1.2. No image creation, so no authentication snapshot |
| Secure Shell (SSH) connection mode | Your desktop Orca dials the host, so it needs the Mac awake. Does not solve the problem |
| Application load balancer endpoint | Creates new inbound exposure in a healthcare non-production tenant to carry an agent control channel |
| Tailscale | Clean, and you already run a tailnet, but it adds an auth key to manage. You chose SSM instead |

## 3. Implementation phases

### 3.1 Prerequisites

- Refresh the `duploctl` token. The current one returns `Authorization has been denied`.
  The AWS path is healthy — this is the portal token only.
- Install the SSM session plugin on the Mac. It is currently missing.

```bash
brew install --cask session-manager-plugin
duploctl --host https://duplo.cloud.brook.ai --tenant dev01-brook --interactive hosts find
```

### 3.2 Create the host

Model the host specification on an existing tenant host, then apply it. Target shape is
a t3.xlarge on Ubuntu, 4 virtual central processing units and 16 gigabytes of memory,
matching the tenant norm, with the `duploservices-dev01-brook` instance profile so SSM
attaches automatically.

### 3.3 Install Orca

Over `ssm send-command`, install the published Debian package and smoke-check that the
Linux build exposes the `serve` verb.

```bash
curl -fsSL -o /tmp/orca-ide.deb \
  https://github.com/stablyai/orca/releases/download/v1.4.180/orca-ide_1.4.180_amd64.deb
apt-get install -y /tmp/orca-ide.deb
orca-ide serve --help
```

### 3.4 Authenticate Claude inside the host

Interactive, and you run it — an agent has no terminal to type into. Use the device
flow. A browser-callback login binds a loopback port your Mac cannot reach and will
hang.

Credentials are created inside the runtime. Nothing is copied from your Mac's `~/.claude`,
which carries host-specific state that breaks when transplanted.

### 3.5 Run `orca serve` under systemd

A unit file pinned to port 7331, advertising `ws://127.0.0.1:7331` as the pairing
address so it matches the forwarded local port. Enabled at boot.

### 3.6 Pair and verify

```bash
aws ssm start-session --target <instance-id> \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["7331"],"localPortNumber":["7331"]}'

orca environment add --name dev01-brook --pairing-code '<code>'
orca orchestration worker-start --on dev01-brook --task <id> --agent claude
```

## 4. Assumptions and open risks

- **Unverified:** that the Linux `orca-ide` build supports `serve`. Strongly implied by
  the skill's own Linux guidance, but it gets smoke-tested at 3.3 before anything
  depends on it.
- **Unverified:** that your role holds `ssm:SendCommand` and `ssm:StartSession`. Safe to
  test only on the new host, not on existing tenant machines.
- **Unverified:** that Orca accepts a loopback pairing address. The Orca documentation
  explicitly blesses an SSH-forward endpoint, which is the same shape.
- **Accepted cost:** the port-forward is a foreground process and must be restarted on
  each wake. That was your call over introducing a Tailscale key. It wraps into a
  one-line script.
- **No patient data.** This is a development tenant and these hosts carry repository
  work only.

## 5. Numbers

```text
Tenant                dev01-brook
AWS account           173008660334
Region                us-east-1
VPC                   nonprod, 10.221.0.0/16
Mutating EC2 calls    0 of 5 permitted        (tested 2026-08-13)
Custom images owned   0
SSM instances online  11
Orca release          v1.4.180, Linux assets present
Instance              t3.xlarge, 4 vCPU / 16 GB
Compute cost          ~$0.166/hr, ~$121/mo if never stopped
Storage cost          ~$8/mo, 100 GB gp3
```

## 6. Decision needed

Phase 3.1 needs you at the keyboard for the `duploctl` login, and 3.4 needs you for the
Claude device flow. Everything else is scriptable from here.

Approve the spec and confirm the `duploctl` token is refreshed, and the host goes up.
