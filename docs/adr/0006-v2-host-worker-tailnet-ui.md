---
status: accepted
date: 2026-09-25
---

# v2 installs as host or worker; the host UI is reachable on the tailnet

v1 stays ADR 0001: one GPU workstation, the UI bound to `127.0.0.1` only, one Run at a time. v2 adds a tailnet swarm without putting a UI on every machine.

Lab 3090s develop and validate with pixi. The container is the scientist install. The medium follows who is installing, and the machine is still one of two roles:

- **Host.** Serves the UI, owns the Run, keeps the policy, and dispatches Scoring rounds. It may include itself in the scoring set. It listens on `127.0.0.1` and on its Tailscale address. It does not listen on the public LAN.
- **Worker.** Runs BioSmart with the Scorer environments and the Doctor CLI. It does not install or serve the UI, and it does not run the policy. It accepts `prepare`, `score`, and `flush` from a host on the same tailnet.

A scientist starts a Run from their own computer by opening the host's tailnet URL in a browser. That computer does not need BioSmart installed. The policy stays on the GPU host.

The scientist chooses which discovered workers, and how many, score the Run. The host dispatches inside that set. The set is fixed at Start. A worker is offered when BioSmart is running there and the Doctor blocking checks pass. A busy worker stays visible and is not selectable until the Run releases it. Busy covers prepare, score, and flush. Tailnet membership is the trust boundary. There is no second token.

One Run lives on the host. Workers return scores and Scorer working files into the host Run folder, then drop their scratch. If a worker dies during a Scoring round, the host retries that Scoring round once on another selected worker, then marks those Candidates failed and continues the Run. Pause flushes workers back to the host and releases them. Resume prepares the same set.

v1 does not grow discovery, a worker picker, or a tailnet client. The seam is local `prepare`, `score`, and `flush`. ADR 0005 is the JSON-lines transport for a persistent Scorer worker.

## Considered options

- Keep the UI on localhost only, so the scientist sits at the GPU box. Rejected for v2. They should be able to start a Run from their own computer.
- Install the full UI on every worker. Rejected. A worker only scores.
- Make the scientist's laptop the host and run the policy there. Rejected. The policy stays on a GPU workstation. The laptop is a browser.
- Add a shared lab token on top of Tailscale. Rejected. Tailnet membership is the perimeter, same posture as v1.
- Bind the UI on `0.0.0.0`. Rejected. The extra listener is the Tailscale address, not the LAN.

## Consequences

- ADR 0001 still governs v1. Its "remote access is out of scope" line does not govern v2.
- A worker install does not include the static UI. A host install serves it.
- Joining the tailnet is what grants access to the UI and to dispatch. A machine that should not start Runs must stay off that tailnet.
- The host Run folder remains the archive. Worker scratch is not a second copy of record.
- Discovery transport is whatever can see a BioSmart worker on the tailnet. This ADR does not pick the wire format beyond the Scorer calls.
