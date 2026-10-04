# Self-hosting

How to run your own instance, keep it safe and up to date, and make it
reachable from outside your network. You need a machine that stays on, with
Docker and its Compose plugin. Everything runs from one released image and a
PostgreSQL container.

## Install

Fetch the two files an instance needs into a directory of its own:

```bash
mkdir garmin-analyzer && cd garmin-analyzer
curl -fsSLO https://raw.githubusercontent.com/wedsel2/garmin-analyzer/main/compose.yaml
curl -fsSL -o .env https://raw.githubusercontent.com/wedsel2/garmin-analyzer/main/.env.example
```

Edit `.env`:

| Setting | What to put in |
|---|---|
| `APP_IMAGE` | Remove the `#` and put in a version from the [releases](https://github.com/wedsel2/garmin-analyzer/releases), without the `v`. Naming a version means an update happens when you choose. |
| `POSTGRES_PASSWORD` | A long random password. It is only used between the containers. |
| `TOKEN_ENCRYPTION_KEY` | The key that the command below prints. It needs the two settings above. |

```bash
docker compose run --rm --no-deps web generate-key
```

Then start it:

```bash
docker compose up --detach
```

This starts the database, brings its tables up to date, serves the web
interface on <http://localhost:8000> and starts the worker that collects.

To check a released image before running it, see "Verify a released image" in
the [pipeline document](ci-pipeline.md).

## First account

Open the web interface and create the administrator account. **Do this before
the instance can be reached by anyone else**: whoever opens a fresh instance
first becomes its administrator.

If you lose the administrator's password, set a new one on the machine itself:

```bash
docker compose run --rm web user-password you@example.com
```

## Link Garmin

Choose **Link Garmin** on the overview. You sign in at Garmin in your own
browser, with your verification code if Garmin asks for one, and paste the
address of the page you end on back into the form, within a minute. The
instance never sees your Garmin password. It stores the access it receives
encrypted with `TOKEN_ENCRYPTION_KEY`.

The worker picks up a new link within a minute, fetches the last two weeks, and
from then on syncs every linked user once an hour. `SYNC_INTERVAL_MINUTES` in
`.env` changes that. To fetch older history:

```bash
docker compose run --rm web collect you@example.com --since 2024-01-01
```

It pauses a second between requests, so a year takes a while. It can be
interrupted and started again; it only fetches what is still missing.

When Garmin stops accepting the link, the overview says so. Link again on the
same page. A user stays linked to the Garmin account of their first sync.

## More users

Invite someone on the **Users** page. It shows a link to pass on, once, with
which they choose their password; the link works for seven days. The same page
makes a new link for someone who lost their password, and removes users with
their data. Each user links their own Garmin account and sees only their own
data.

## The coach

On the **Coach** page a user can have Claude, an AI model of Anthropic, write a
report on their figures and goals with advice for the coming week. It is off
for every user until they turn it on themselves, on a page that lists what is
then sent to Anthropic. Nothing is sent for anyone else, or without asking.

A report needs an Anthropic API key, which costs money per report. A
membership of claude.ai does not include it; the key and its credit come from
<https://platform.claude.com>.

- Put `ANTHROPIC_API_KEY` in `.env` and run `docker compose up --detach`, and
  you pay for every user. Each user gets at most `COACH_REPORTS_PER_DAY`
  reports in 24 hours, 3 unless you set another number.
- Or leave it out: a user can enter a key of their own on the Coach page. It is
  stored encrypted with `TOKEN_ENCRYPTION_KEY`, is used instead of yours and
  has no limit.

`COACH_MODEL` names another Claude model than the default.

Without any key the page still helps: **Ask Claude yourself** gives a user
their figures and goals as a text to paste into a chat with Claude, on
whatever membership they have. The instance sends nothing then.

## Back up

Two things make up an instance: the database and `.env`.

```bash
docker compose exec -T db pg_dump -U garmin --format=custom garmin > garmin.dump
```

Keep `garmin.dump` and a copy of `.env` somewhere else, and not next to each
other if you can: the dump holds everyone's health data and the encrypted
Garmin access, and `.env` holds the key to that access. Without the key the
data is still there, but every user has to link Garmin again.

To restore, on a new machine or over what is there, put `compose.yaml` and the
`.env` you kept in place, then:

```bash
docker compose stop web worker
docker compose up --detach --wait db
docker compose exec -T db pg_restore -U garmin -d garmin --clean --if-exists < garmin.dump
docker compose up --detach
```

## Update

Put the new version in `APP_IMAGE` and run:

```bash
docker compose pull
docker compose up --detach
```

Starting the web service brings the tables up to date; the worker waits for
that. Make a backup first: an update can change the tables, and going back to
an older version afterwards needs the dump from before.

## Replace the encryption key

For example when `.env` may have been read by someone else. In
`TOKEN_ENCRYPTION_KEY`, put a new key first and the old one after a comma, then:

```bash
docker compose up --detach
docker compose run --rm web collect
```

`collect` stores the access of every user it syncs with the new key. After
that, remove the old key from `.env` and run `docker compose up --detach`
again. A user whose link needed a new sign-in at that moment has to link again
anyway. A user's own API key for the coach is stored with the new key when
they ask for a report; one that was not used in the meantime has to be entered
again.

## Reach it from your network

By default the web interface listens on the machine itself only. To reach it
from other devices at home, set in `.env`:

```bash
WEB_BIND=0.0.0.0:8000
```

The number after the colon is the port on your machine. When 8000 is taken,
choose another one, such as `0.0.0.0:8010`; nothing else changes, and the
addresses below get that port.

That is plain HTTP, which is fine for looking around at home but has two
limits. Passwords cross your network unencrypted. And browsers only install a
site as an app, and only run its offline page, over HTTPS. For both, publish
the instance through a proxy that provides HTTPS.

## Publish it through a Cloudflare tunnel

The reference setup ([ADR 11](adr/0011-compose-deployment-behind-cloudflare-tunnel.md))
is a hostname on a Cloudflare tunnel, with Cloudflare Access in front. Nothing
is opened on your router. Any other reverse proxy that provides HTTPS works the
same way as far as the instance is concerned; only the first two steps differ.
One tunnel serves several hostnames, so an existing one will do.
The names of pages in Cloudflare's dashboard change now and then, so the steps
say what to make and not where to click.

1. **Access in front of it.** Before the hostname exists, add a self-hosted
   Access application for it, for example `garmin.example.com`, and attach a
   policy that allows the email addresses of you and your users. Made in this
   order, the sign-in page of the instance is never open to the internet. A
   visitor passes Cloudflare's check first and then signs in to the instance:
   two steps, on purpose, as Access keeps strangers away from the instance
   altogether and the instance decides whose data someone sees.

   Make the application for this one hostname, not for a wildcard or the whole
   domain: an app that cannot show Cloudflare's sign-in screen, such as the one
   of Home Assistant, stops working behind Access. When you invite someone
   later, add their address to the policy too, or Cloudflare stops them before
   they reach their invite.

2. **A hostname on the tunnel.** Add the public hostname to your tunnel, with
   as its service `http://` followed by the address and port where
   `cloudflared` reaches the web interface. When `cloudflared` runs on the same
   machine, and not in a container, that is `http://localhost:8000`. When it
   runs in a container or on another machine, such as the Cloudflared add-on of
   Home Assistant, `localhost` is not this machine: set `WEB_BIND` to an
   address of this machine that the other one can reach, and use that. Leave
   the host header as it is: the instance needs to see the public hostname.

   Open the hostname in a private window. Cloudflare's screen should come
   before the sign-in page of the instance.

3. **Trust the proxy.** Open the hostname once and look at the log:

   ```bash
   docker compose logs web | grep "forwarded headers"
   ```

   When the instance does not trust the proxy, a line names the address the
   request came from. Put that address in `.env`, for example as below, and
   run `docker compose up --detach` again:

   ```bash
   FORWARDED_ALLOW_IPS=172.18.0.1
   ```

   The address is the one Docker passes on. On a Linux host with `cloudflared`
   on another machine it is the address of that machine. With `cloudflared` on
   the same machine it is usually the gateway of the Docker network. Until this is set the session cookie is not marked
   `Secure`, links to set a password do not use HTTPS, and failed sign-ins of
   all users are counted together.

   Everything that connects from an address in this list is believed about who
   the visitor is. When the address is that of the Docker network, that can be
   every device that reaches the port. So keep `WEB_BIND` as narrow as the
   setup allows: the default when `cloudflared` runs on the same machine.

4. **Check.** Sign out and in again through the hostname. No new line about
   forwarded headers should appear in the log, and a link made on the Users
   page should start with `https://` and your hostname.

Visitors who reach the port directly, at home, do not pass Access. For them
only the sign-in of the instance applies.

## Install it on Android

Open the hostname in Chrome, sign in, and choose **Add to Home screen** and
then **Install** in the menu. The site then opens in a window of its own. It
needs a connection: without one it shows a page that says so. Nothing of your
data is kept on the phone.

This works with Cloudflare Access in front and needs nothing extra there.
Should Chrome offer only a shortcut and not an install, check whether Access
keeps it from the icons: a second Access application for the same hostname with
the path `static/icon-*` and a policy of the kind **Bypass** for everyone lets
them through. Those files are the same for every instance and hold no data.

## What it cannot do

- **Show inside another site**, such as a panel in Home Assistant. The instance
  forbids being framed. A link from there works.
- **Work without a connection.** See above.
- More limits of collecting are in the [roadmap](roadmap.md#known-limits-of-the-collector).
