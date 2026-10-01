---
name: adr
description: Write a new Architecture Decision Record in docs/adr/ in the project format and update the index. Use when a decision changes the architecture, a technology choice, the data model, security posture or the pipeline, or when the user asks to record a decision.
---

# Writing a decision record

1. Find the next number: list `docs/adr/` and add one to the highest prefix.
2. Create `docs/adr/NNNN-short-kebab-title.md` with exactly these sections:

   ```markdown
   # N. Title stating the decision

   - Status: Proposed | Accepted | Superseded by [N](file.md)
   - Date: YYYY-MM-DD

   ## Context

   The problem and the constraints that force a decision. Facts, not the answer.

   ## Decision

   What we do, in the present tense. Specific enough to check code against.

   ## Alternatives considered

   - **Option**: why it was not chosen.

   ## Consequences

   What becomes easier, what becomes harder, and what follow-up it creates.
   ```

3. Add a row to the table in `docs/adr/README.md`.
4. If the decision changes the design, update `docs/architecture.md` in the same
   change. If it changes the pipeline, update `docs/ci-pipeline.md`.

## Rules

- One decision per record. Keep it under a page.
- Use `Proposed` when the decision still depends on a spike or on the user's
  confirmation; say what would confirm it.
- Never rewrite an accepted record. To change a decision, write a new record and
  set the old one's status to `Superseded by` with a link.
- Alternatives must be real options that were weighed, with the actual reason
  they lost.
