# Ammar AI

A private React/FastAPI chat app, created by Ammar and powered by the existing Qwen3 model on your Mac. The web app runs in Docker; Ollama stays native on 127.0.0.1:11434. No Ollama container, second Ollama instance, or model download is needed.

## Access for your group

Share one registration code with your group. Everyone chooses their own username and password. The app allows **10 accounts total, including Ammar's existing account**. Existing accounts count toward the limit. When all places are filled, registration closes and existing users can still sign in.

Create or replace the shared code:

```sh
docker compose exec app python -m scripts.invite
```

The first line is the code. The second line shows remaining places. The same code works for every new member until the account limit is reached. It has no automatic expiry. Running this command again replaces the code and revokes previous unused invitations; it does not change existing accounts or passwords. Only the code's SHA-256 digest is stored. Send the code privately with the public URL.

New members open the URL, click “Have an invitation? Join here”, enter the shared code, and choose a unique username and a password of at least 12 characters. Afterwards they sign in with their own credentials; they do not need the code again. The limit counts accounts, not simultaneous requests. One generation runs at a time to conserve RAM; other users receive a busy message and can retry.

## Current public address

```sh
cat .runtime/public-url.txt
```

The address is temporary and changes when the sharing controller restarts. Your Mac must remain online, powered, with its lid open. The launcher prevents idle sleep while running. Quick Tunnels have no uptime guarantee.

## Install and first Docker migration

Prerequisites: Docker Desktop, Python 3.12+, uv, Node 22+ and npm for local development, cloudflared, and the existing running Ollama with qwen3:4b installed.

```sh
uv venv --python 3.12
uv pip install -r requirements.lock
npm ci --prefix frontend
npm run build --prefix frontend
cp .env.example .env
brew install cloudflared
open -a Docker
docker compose build
```

Copy .env.example only on first installation; preserve an existing .env. Before first migration, stop any native FastAPI server and sharing controller:

```sh
.venv/bin/python -m scripts.share --stop
.venv/bin/python -m scripts.docker_setup
```

The migration safely copies accounts, sessions and invitations to data/localai.sqlite3, retaining the original database. Do not rerun migration with an unrelated DATABASE_PATH or overwrite an existing data directory. data/ is excluded from Git and the image; back it up privately. LOCALAI_UID/GID map the container to the Mac's file owner.

## Start Docker with public sharing

Ensure port 8000 is free and Docker Desktop and Ollama are running:

```sh
.venv/bin/python -m scripts.share --background --curl-provision --docker
cat .runtime/public-url.txt
```

The launcher creates a temporary Cloudflare URL, sets APP_ORIGIN and COOKIE_SECURE=true in .env, and starts the Docker app. FastAPI serves React from the image. The launcher and cloudflared remain small native host processes. The --curl-provision option works around cloudflared's provisioning timeout observed on this Mac; credentials stay in memory.

Open the printed HTTPS address. With public settings, use that address instead of localhost to sign in. Each controller restart gives a NEW URL; share the new address with your group. Existing accounts and passwords persist, but users sign in again at the new hostname.

Stop public sharing and its Compose application:

```sh
.venv/bin/python -m scripts.share --stop
```

After source changes, rebuild and recreate only the web container while the sharing controller stays running:

```sh
docker compose build
docker compose up -d --no-deps app
```

The controller now starts Docker detached, so web-container updates preserve the public URL. Restarting the tunnel controller itself still creates a new temporary address.

## Local-only Docker startup

Stop sharing first, set APP_ORIGIN=http://localhost:8000 and COOKIE_SECURE=false in .env, then:

```sh
docker compose up -d
docker compose ps
```

Open http://localhost:8000. Stop with `docker compose stop`. Docker binds its published port only to 127.0.0.1. The container runs without root privileges with a read-only image filesystem, dropped capabilities and a 512 MB memory cap. Its writable paths are the persistent /data mount and temporary /tmp.

Docker Desktop forwards host.docker.internal:11434 to the existing native Ollama. The backend accepts only that URL or http://127.0.0.1:11434 as its configured Ollama target. Keep Ollama listening only on localhost; do not set OLLAMA_HOST=0.0.0.0, expose 11434, or use router port forwarding.

## Model and memory settings

The server always selects qwen3:4b and calls /api/chat with stream=true. Simple questions receive concise answers by default; ask explicitly for a tutorial or more detail when needed. Context is fixed at 4096 tokens. Default output is 1024, configurable with OUTPUT_TOKENS=64..2048 in .env and per request in the interface. Oldest complete turns are trimmed using a conservative UTF-8 byte budget that reserves room for output; oversized single turns are rejected. Ollama remains the final tokenizer authority.

The installed tag is Qwen3-4B-Thinking-2507, GGUF Q4_K_M, with thinking.values=[true]. These weights cannot disable reasoning. The backend detects this metadata and requests structured thinking output so Ollama separates reasoning from the final answer. By default only the final answer is sent to the browser; the UI shows “Preparing answer…” while the model reasons. Enable “Show thinking” to see a separate collapsed section. Models supporting both modes still receive the requested thinking boolean. Thinking and the final answer share the output budget; increase Output tokens to 2048 if a reply is cut off. Context remains 4096 and no weights have been changed or downloaded.

Conversations remain in tab memory and are cleared on sign-out/reload. SQLite stores accounts, hashed passwords, hashed invite/session tokens and throttling state, not chats. Passwords use Argon2id; public cookies are Secure, HttpOnly and SameSite=Strict. Sessions expire after 24 hours. Mutations require an exact Origin header; Host is restricted. Login/registration attempts are limited per username. The shared-code cap is checked in the same SQLite write transaction as account creation, including legacy operator/test invitations, so simultaneous signups cannot exceed 10.

## Verification commands

```sh
.venv/bin/python -m pytest -q
npm run build --prefix frontend
npx --prefix frontend playwright test --config frontend/playwright.config.js recovery.spec.js
docker compose ps
docker compose logs --tail=50 app
.venv/bin/python -m scripts.live_test --loopback
```

The live test exercises actual Docker FastAPI and Ollama, creating and removing a temporary user. It uses the configured public Host/Origin and explicitly supplies the returned session cookie over local HTTP. Full browser and live registration tests require a free account place; test fixtures do not count once cleanup completes. Do not run generation tests simultaneously because only one generation is allowed.

Public checks, with the sharing controller running:

```sh
.venv/bin/python -u -m scripts.public_test
PLAYWRIGHT_BASE_URL="$(cat .runtime/public-url.txt)" npx --prefix frontend playwright test --config frontend/playwright.config.js chat.spec.js
```

Browser installation if necessary:

```sh
npx --prefix frontend playwright install chromium
```

Check the existing model directly:

```sh
curl -N http://127.0.0.1:11434/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3:4b","messages":[{"role":"user","content":"Say hello"}],"think":false,"stream":true,"options":{"num_ctx":4096,"num_predict":512}}'
lsof -nP -iTCP:11434 -sTCP:LISTEN
```

See TEST_RESULTS.md for what actually ran and its limitations. Temporary tunnel/network requests have sometimes taken about a minute to start on this connection. The UI includes recovery handling for interrupted/malformed responses and unexpected display errors; refresh after frontend updates to load the latest version. Automatic scrolling is optional and cannot terminate the chat. Unexpected render errors show their full message and build identifier; an authenticated diagnostic report (error metadata and component stack, not chat history) is written to the Docker application log.

## Future domain-based hosting

A domain is optional for temporary sharing. For a stable address later, create a named Cloudflare Tunnel and use deploy/cloudflared.yml.example. Set APP_ORIGIN to the HTTPS hostname and COOKIE_SECURE=true, then recreate the Docker app with those settings. Tunnel only port 8000. Additional email restrictions can be configured with Cloudflare Access when using a managed hostname. Keep tunnel credentials outside this repository.

References: https://docs.ollama.com/api/chat · https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/ · https://docs.docker.com/desktop/features/networking/networking-how-tos/

To verify clean final-answer delivery through the actual public app:

```sh
npx --prefix frontend playwright test --config frontend/playwright.config.js final-answer.spec.js
```

## Portfolio review — 3 November 2026
Malformed or negative Content-Length now returns HTTP 400. Backend regression suite: 14 tests passed on Python 3.12 with the patched lockfile. CI runs backend checks; browser, Docker and live Ollama tests were not rerun in this review. requirements.lock is the reproducible dependency snapshot.
