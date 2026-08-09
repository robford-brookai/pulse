# Tasks — bf0a-archaeology-access

Annotation format, read by `task dispatch` and checked by G_MECE:
`[model | deps | lane | wave]`, with `serial:` carrying its justification where set. Linear ids
get bracketed in after `task linear:sync`. Tests ship in the same commit; all tests
socket-blocked — the Mongo client is faked at the driver boundary.

---

## 1. Access seam

- [x] 1.1 Scaffold `packages/archaeology` as a workspace member and build the read-only client
      factory: connection from the documented env var names only, streamline-inherited driver
      and TLS/retry posture (cite the source path in the README and
      `docs/contracts/consumes.md`), refusal when the resolved user detectably holds write
      roles. Tests: missing env vars fail fast naming names; write-role fixture refused;
      socket-blocked throughout.
      `[model: opus | max: fable | deps: — | lane: repo_change | wave: 0]`
      `serial: workspace_roots` — edits the root workspace manifest. Model `opus`: the
      streamline pattern inheritance must be read correctly, per the batch doc's routing.
- [ ] 1.2 Smoke CLI (`python -m archaeology.smoke --list-collections`, names only, exit status
      is the receipt), README (read-only-Atlas-role hard precondition, env var names as the
      BF-0b interface, bulk-extraction-seam note), and the credential-material gate wired as a
      test (no `mongodb+srv://…@` material anywhere in the tree). Tests: CLI happy path against
      the faked client; credential grep green.
      `[model: sonnet | deps: 1.1 | lane: repo_change | wave: 1]`
