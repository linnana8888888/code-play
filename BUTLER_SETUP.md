# Butler Setup — itch.io publishing credentials

One-time setup for the `publisher` agent to push builds to itch.io. Do this yourself;
don't delegate to an agent. The API key lives on your machine only.

## 1. Create an itch.io account (skip if you have one)

- Go to https://itch.io/register
- Sign up with the email you want game receipts going to
- Pick a username — this becomes your publisher handle. It appears in every URL:
  `https://<your-username>.itch.io/<game-slug>`. Choose it carefully; renames break links.
- Verify your email

## 2. Install butler

Butler is itch's publishing CLI. macOS:

```bash
# Option A: Homebrew (cleanest)
brew install butler

# Option B: direct download (if you don't want Homebrew managing it)
curl -L -o butler.zip https://broth.itch.ovh/butler/darwin-amd64/LATEST/archive/default
unzip butler.zip -d ~/bin/butler-app
chmod +x ~/bin/butler-app/butler
ln -sf ~/bin/butler-app/butler /usr/local/bin/butler
```

Verify:
```bash
butler -V
# should print: butler, version X.Y.Z
```

## 3. Log in (generates the API key on disk)

```bash
butler login
```

This opens a browser, you authorize butler, and itch writes a token to
`~/.config/itch/butler_creds`. **This is your API key.** Treat it like a password.

Read it back:
```bash
cat ~/.config/itch/butler_creds
# prints something like: abcd1234...
```

Copy the token into your Code Play `.env`:
```bash
# ~/code-play/.env   (or wherever the project lives)
BUTLER_API_KEY=abcd1234...
ITCHIO_USERNAME=<your-username>
```

Make sure `.env` is in `.gitignore`. It is by default in this project — verify with
`grep -n ".env" .gitignore`.

## 4. Create a placeholder game page (recommended)

Butler refuses to push to a game page that doesn't exist yet. Create a draft:

1. https://itch.io/game/new
2. Kind: **HTML**
3. Classification: Game
4. Title: anything — the publisher will rename it at first push
5. Project URL: pick a slug. You can also wait and let the publisher create it on first push.
6. Visibility: **Draft** — keep it draft until the first real publish
7. Pricing: Free
8. Save

You do NOT need to upload anything yet. The `publisher` agent will call
`butler push <zip> <username>/<slug>:html5` and that populates the page.

## 5. Smoke-test butler from your machine

Before you let an agent touch it, prove it works yourself:

```bash
# Zip butt-shooting-game-v2 as a practice push
cd artifacts/butt-shooting-game-v2
zip -r /tmp/smoke-test.zip index.html

butler push /tmp/smoke-test.zip <your-username>/smoke-test:html5
# butler should print upload progress + "Build is processing, should be up in a bit!"

butler status <your-username>/smoke-test
# should list the channel and a build ID
```

If that worked, the agent path will work the same way.

**Clean up:** once smoke-tested, either delete the `smoke-test` page on itch.io, or
leave it as a draft — your call. You can reuse it as a testbed for publisher changes.

## 6. What the `publisher` agent does with the key

- Reads `BUTLER_API_KEY` from `.env` via the project's existing secret loader.
- Executes `butler push` and `butler status` through the restricted
  `itchio_publish` tool.
- Every call is gated by the approval queue — the key cannot be used without a
  human clicking approve, same pattern as `git_push`.
- The key is never logged, never echoed in agent transcripts, never sent to an
  LLM request body. If you see it surfacing anywhere, that's a bug — flag it.

## 7. Rotation

If the key ever leaks:
```bash
butler logout         # invalidates the current token on the server
butler login          # re-auth, new token written to ~/.config/itch/butler_creds
```
Then update `.env` with the new value. itch has no token UI — `butler logout` is
the only way to revoke.

## 8. What this does NOT cover

- **GitHub Pages** — no new credentials needed; publisher uses the existing git
  creds and `gh-pages` branch pattern.
- **Roblox Open Cloud** — separate setup (API key at
  `https://create.roblox.com/dashboard/credentials`, scoped to a specific
  universe). Do that when you're ready to ship the Roblox pipeline; not needed for v1.

## Reference

- butler docs: https://itch.io/docs/butler/
- itch HTML5 game guide: https://itch.io/docs/creators/html5
