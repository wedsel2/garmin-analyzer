# 21. The coach is a report that Claude writes on request, opt-in per user

- Status: Accepted
- Date: 2026-10-04

## Context

Phase 8 adds analysis and training advice by a language model. The data is
health data of several people on one instance, and the model runs at Anthropic,
so using it means sending figures off the instance: until now nothing left it.
Every request costs money, on someone's API key. A request takes up to a minute
or two, and the instance sits behind a Cloudflare tunnel that ends a request
after 100 seconds. The pages allow no scripts but our own and render no markup
from data. A membership of claude.ai does not pay for requests to the API, so
an owner or a friend who has one would pay a second time.

## Decision

- The coach is a **report on request**: a user presses a button on the Coach
  page and one request to the Claude API writes how they are doing and what to
  do in the coming seven days. Nothing is sent on a schedule.
- **Without a key, a user takes the text along.** The Coach page offers the
  same figures with the coaching instructions as a text to copy or save, to
  paste into a chat with Claude. The instance sends nothing, so this needs no
  opt-in and no key, and works with any membership.
- **Opt-in per user.** `coach_settings.enabled_at` is empty until the user turns
  the coach on, on a page that lists what is sent. Without it no request is
  made, also not one that was started before it was turned off. Turning it off
  keeps the reports; the user removes them with a button of its own.
- **What is sent** is put together in one function, `coach.figures`, as text:
  28 days of daily metrics, weekly averages of the 12 weeks before, Garmin's
  latest training status, readiness, VO2 max, predicted race times and age, the
  activities of 28 days as summary figures, hours per week and sport, and the
  goals with the names and notes of events. **Not sent**: name, email address,
  names of activities, places, positions, intraday samples and raw responses.
- **Only `claude.py` imports the Anthropic library**, as only `garmin.py`
  imports Garmin's. It gets a key, the instructions and the text, and knows no
  user. Tests replace it or give the library a transport that answers locally;
  no test reaches Anthropic.
- **Two keys.** `ANTHROPIC_API_KEY` of the instance pays for every user, up to
  `COACH_REPORTS_PER_DAY` (3) reports per user in 24 hours; a failed one
  counts only when Claude did answer, as that is paid for. A user can store a key of their own, which is used instead and has no
  limit. It is encrypted with `TOKEN_ENCRYPTION_KEY` like the Garmin tokens,
  never shown again, and encrypted with the newest key when it is used (ADR 14).
  Without either key the page says so and nothing else changes.
- **Written after the request.** Asking stores a report as `pending` and
  answers at once; the web process writes it in a background task and the page
  asks again every few seconds until it is there. One report per user at a time.
  A report that is still pending after 15 minutes, after a restart for one,
  counts as failed.
- **The answer has a fixed shape** (structured output): a summary, three texts,
  a plan with an entry per day and a list of things to watch. It is stored as
  JSON in `coach_reports` and shown as text, never as markup. The last 30
  reports per user are kept.
- The model is `claude-opus-5-5` unless `COACH_MODEL` names another. The request
  lets Anthropic answer with another model when the first declines.
- The key and the figures are never logged; an unforeseen error is logged by
  its kind only.

## Alternatives considered

- **A weekly report written by the worker**: always something to read, but it
  sends health data and spends money without anyone asking. Can be added on top
  of this for users who want it.
- **Calling Claude on the owner's membership**, through Claude Code on the
  server: a membership is for one person's own use and not for an app that
  serves others, and it would put a Node tool in the image (ADR 7).
- **A chat in which Claude looks up data with tools**: more flexible, but needs
  streaming, stored conversations and a tool loop, and its cost per user has no
  natural bound. The report covers what the goals of phase 7 were added for.
- **One key only**, of the instance or per user: the first makes the owner pay
  for everyone without a way out, the second makes every friend open an
  Anthropic account before they can try it.
- **On for everyone once the instance has a key**: one setting, but the owner
  would decide that other people's health data leaves the instance.
- **Writing the report inside the request**: no pending state, but a slow
  answer dies at the tunnel after 100 seconds, having been paid for.
- **Free text or Markdown as the answer**: nicer to write for the model, but
  needs a renderer and a sanitiser for text that came from outside.

## Consequences

- An instance without a key behaves as before, and self-hosting needs nothing
  new. With a key, the owner's cost is bounded by users times the daily limit.
- Anthropic receives health figures of users who opted in, under its API terms.
  They carry no name, but notes of events are free text and go as written.
- A restart of the web service loses a report that was being written; it shows
  as failed after 15 minutes and did not count.
- A user key that was not used while the encryption key was being replaced
  cannot be read afterwards and has to be entered again.
- What a user pastes into a chat is theirs to send; the answer is not kept in
  the app. A connector through which Claude reads the figures itself is a
  later step with a record of its own.
- A change to what is sent is a change to `coach.figures`, to the list on the
  Coach page and to this record.
- The report reads days in UTC, like the pages it draws on.
