# Verification — 2026-10-29

Executed on this Mac against the existing Ollama at 127.0.0.1:11434.

- Initial direct qwen3:4b inference: real NDJSON token chunks and final done event received. The 32-token diagnostic reached its output limit.
- Model inspection: GGUF Q4_K_M, 4.0B, Qwen3-4B-Thinking-2507, thinking values [true]. Both think:false and /no_think failed to disable reasoning. Genuine non-thinking mode is unavailable with the installed weights.
- `.venv/bin/python -m pytest -q`: 6 passed; one Starlette/AnyIO deprecation warning. Covers invite consumption, login/logout, unauthenticated rejection, origin/host/body limits, request validation, throttling, streamed payload and multi-turn forwarding, error cleanup, secure cookies, thinking forwarding, history budget.
- `.venv/bin/python -m scripts.live_test`: passed against actual FastAPI/Ollama. Two turns produced 508 and 510 content chunks; second response recalled Mira. Temporary user removed.
- `npm run build --prefix frontend`: passed with Vite 6.4.5, including final CSS refinement.
- npm install audit after Vite update: zero reported vulnerabilities.
- `npx --prefix frontend playwright test --config frontend/playwright.config.js`: 1 passed (43.3 seconds). Actual Chromium, FastAPI and Ollama; invitation registration, login, default thinking preference off, progressive content while Stop remains visible, two-turn recall, desktop/mobile screenshots, no horizontal page overflow, logout, no page errors. Initial run exposed registration state persisting after logout; fixed and rerun passed. Chromium was installed to run this test.
- `lsof -nP -iTCP:11434 -sTCP:LISTEN`: existing Ollama PID 6446 bound to 127.0.0.1 only.

No model downloads, model mutations, or additional Ollama instances. Temporary FastAPI server stopped after verification. Cloudflare account setup, tunnel routing, external TLS/access policy, and external streaming were not executed or tested. This workspace was empty; implementation was created here.

## Public sharing verification — 2026-10-29

Cloudflared 2026.10.5 installed; a Quick Tunnel is now running in the background under scripts.share with FastAPI and idle-sleep prevention. This supersedes the earlier statement that external access was untested. .env now contains the current public HTTPS origin and COOKIE_SECURE=true. Both application and Ollama listeners remain bound only to 127.0.0.1.

- Public homepage: HTTP 200.
- Default cloudflared API provisioning repeatedly timed out. Direct curl provisioning succeeded; the launcher supports --curl-provision and supplies its API response once over loopback to cloudflared. Credentials remain in memory.
- `.venv/bin/python -u -m scripts.public_test`: PASS against actual public HTTPS URL. Invitation registration, secure-cookie login, two real chat turns, name recall, logout, and temporary-user cleanup completed.
- Timed streaming: first turn 232 chunks over 10.71 seconds; second turn 373 chunks over 17.74 seconds. First-chunk waits were 61.14 and 62.68 seconds. Temporary tunnel/network access is slow on this connection.
- The first public browser run verified registration/login, progressive rendering, two-turn recall, screenshots/mobile width, then failed the 5-second logout assertion because the response had not arrived. Its logout timeout was increased to 60 seconds. A subsequent browser run was interrupted after it collided with the curl test and received the expected single-generation 429. No complete public browser pass is claimed. The separate public curl test above completed successfully.
- An earlier public httpx test was interrupted by a Cloudflare tunnel reconnection and failed; no pass is claimed for it.
- Final `.venv/bin/python -m pytest -q`: 6 passed; tests now explicitly isolate local host/origin/cookie settings from the deployed .env.

User-requested sharing is intentionally left running. Stop with `.venv/bin/python -m scripts.share --stop`. Restart with `.venv/bin/python -m scripts.share --background --curl-provision`; each restart creates a different URL. The current URL is in .runtime/public-url.txt. The first-account invitation was provided privately in chat and is single-use, expiring in 48 hours. No model or Ollama process was changed.

## White-screen fix — 2026-10-29

The reported Python question reached /api/chat (HTTP 200), with no logged backend exception. Browser regression testing reproduced a blank React root when Array.prototype.at is unavailable: the response-finalization updater threw while accessing old.at(-1). This is a confirmed application defect and a plausible cause of the report; the user's actual browser console was not available to prove its exact cause.

Removed Array.at usage, moved draft updates outside message state updaters, validated streamed content types, added a no-text response notice, and wrapped the app in a recoverable error boundary. The running FastAPI static mount serves the rebuilt frontend without restarting the tunnel or changing the URL.

- Before fix: compatibility regression failed and chat root disappeared.
- After fix: `npx --prefix frontend playwright test --config frontend/playwright.config.js recovery.spec.js`: 6 passed (3.2s). Production frontend served through intercepted routes; tests cover busy, empty, malformed JSON, invalid content type, missing Array.at, and an unexpected display exception with a visible recovery screen. These are browser regression tests with simulated API responses, not new model inference tests.
- Final production build passed; running FastAPI homepage references index-k_fvK668.js.

## Docker deployment and Ammar branding — 2026-10-29

Built and started ammar-ai:local via Docker Compose. The interface title, login/sidebar branding, assistant label and footer now show Ammar AI / Created by Ammar, while retaining Qwen model attribution. Docker Desktop was started; no Ollama image, additional Ollama instance or model was downloaded.

- `docker compose build`: passed, native arm64 Node frontend stage and Python 3.12 runtime.
- `.venv/bin/python -m pytest -q`: 6 passed, one existing deprecation warning.
- `npm run build --prefix frontend`: passed.
- Browser recovery/branding regressions: 6 passed (2.8s), including title/brand assertions.
- Existing users, sessions and invitations migrated with SQLite backup to data/localai.sqlite3; exact table equality verified before runtime testing. Original localai.sqlite3 retained. No user data is baked into the image.
- `docker compose ps`: ammar-ai-app-1 healthy, published only as 127.0.0.1:8000->8000.
- Runtime UID 501; container uses the mapped Mac file owner, not root. Read-only image filesystem, dropped capabilities, no-new-privileges, writable /data and /tmp only, 512 MiB memory cap.
- `docker stats --no-stream`: approximately 64.34 MiB used during the check.
- Container -> host.docker.internal:11434/api/ps: HTTP 200 while existing Ollama remains bound to 127.0.0.1.
- `.venv/bin/python -u -m scripts.live_test --loopback`: PASS against actual Docker FastAPI and existing Ollama. Authentication, config, two real streamed turns (304 and 512 chunks), Mira recall, and logout; temporary user removed. Loopback test passes the public Host/Origin and explicitly supplies the Secure session cookie over its local HTTP test transport.

Docker-mode scripts.share and the web container are intentionally left running for the user. The temporary public URL changed during the switch; read .runtime/public-url.txt. Accounts and passwords remain valid at the new origin. The sharing controller and cloudflared stay on macOS; FastAPI and the served React build run inside Docker.

Final public homepage check: HTTP 200 at https://phantom-remedies-jets-keno.trycloudflare.com, serving the Docker-built Ammar AI title and index-CQwsdB2g.js asset.

## Reusable group code and ten-account limit — 2026-10-29

Added a persistent singleton registration-code digest and a global ten-account cap, including existing accounts. Registration checks capacity and creates the account within BEGIN IMMEDIATE, so concurrent requests cannot exceed the cap. The code is reusable and remains valid until the local operator rotates it; rotating clears previous pending invitations without changing users or passwords. Internal legacy/test invitations also obey the global account cap.

- `.venv/bin/python -m pytest -q`: 9 passed. Added tests for the same code registering ten accounts, rejecting account eleven, a legacy invite unable to bypass capacity, login after capacity is reached, simultaneous competition for the final place, and code rotation preserving existing accounts.
- Production React build: passed.
- Browser recovery/branding regressions: 6 passed (3.4 seconds).
- Docker image rebuilt and deployed; ammar-ai-app-1 healthy.
- Actual running Docker API check: two separate temporary accounts registered with the same code, both logged in/out successfully, and the shared-code hash remained unchanged. Temporary users/sessions/throttle records and test code removed afterward. The live database was not filled to ten; cap/race tests ran against isolated test databases.
- Generated the final shared group code through `docker compose exec -T app python -m scripts.invite`. One existing account was preserved; nine of ten places remain. The plaintext group code was provided in chat, not recorded here or in source.
- README updated with shared-code usage and rotation. Full browser tests use isolated operator/test invites so running tests does not rotate the group's real code.

Deployment restarted its temporary Cloudflare tunnel; the current address is in .runtime/public-url.txt. No inference behavior, model weights, or Ollama process changed.

Final public homepage check for the group-code deployment: HTTP 200.

## Repeated Chrome TypeError — 2026-10-29

The user reported the recovery screen with only TypeError and identified Chrome on Mac/Windows. The earlier Array.at reproduction did not establish the actual cause of this new report. No actual user-side error message or stack was available, so the precise original cause remains unconfirmed.

Replaced the scrollIntoView effect with a guarded container scrollTop assignment that always returns undefined. Browser scrolling is optional and cannot break message rendering. The recovery screen now displays the actual error message/stack and build identifier scroll-recovery-2. Authenticated error metadata/component-stack reports go to /api/client-error and the Docker application log; chat history is not included.

- Backend tests: 10 passed, including authentication and length validation for diagnostic reports.
- Browser regression suite: 9 passed (4.4s). Checks busy/empty/malformed responses, missing Array.at, missing/throwing/promise-returning scrollIntoView, and an actual TypeError reaching the recovery screen and reporting endpoint. The initial diagnostic test needed a selector correction because the same message appears in both summary and details; rerun passed.
- Production frontend and Docker builds passed.
- Actual public Chromium test: 1 passed (1.8 minutes), using the real Docker app, public HTTPS tunnel, and existing Ollama. Asked 'What is Python language?', observed a rendered response, a visible composer after completion, no recovery screen and no page errors. Temporary authenticated test account/session cleaned up. Screenshot: test-results/python-public.png. This does not prove the original user's browser environment has no remaining issue.
- Docker remains healthy. Existing accounts and shared-code digest were not rotated or changed.

Upgraded the native sharing controller to start Compose detached. Future Docker app rebuild/recreation can preserve the active tunnel URL. Applying this controller upgrade required one tunnel restart; current URL is in .runtime/public-url.txt. The updated deployment is intentionally left running.

## Final-answer separation and output truncation — 2026-10-29

The user showed Qwen reasoning mixed into the displayed answer and a 512-token cutoff. Direct inference established that think:true returns separate message.thinking and message.content fields for the installed Thinking-2507 weights: the brief FastAPI diagnostic stopped naturally at 414 generated tokens, with 1664 reasoning characters separate from the final answer.

The backend now reads/caches the installed model's thinking-only metadata. For thinking-only weights, it requests structured thinking output even when the UI visibility preference is off. Reasoning is discarded from the browser response unless Show thinking is explicitly enabled. Other model variants still receive the requested boolean. Answer and reasoning remain separate, reasoning is collapsed when requested, and the UI shows Preparing answer while reasoning is hidden. Default output increased to 1024; context stays 4096, maximum output stays 2048. Added a concise default system instruction, including its bytes in the context budget. No weights or Ollama instance changed.

Verification:
- Backend suite: 12 passed, including forced structured output for thinking-only weights, no reasoning text in the default response, and optional reasoning visibility.
- Browser recovery/visibility suite: 11 passed (5.2s), including default 1024 output, reasoning hidden by default, and a separately expandable section when enabled.
- Frontend and Docker builds passed. Web container recreated without restarting the tunnel; public URL and group code preserved.
- Initial public test confirmed hidden reasoning but showed that an unnecessarily long model answer still hit 1024. A concise system instruction was then added. The first automated attempt also encountered Chromium's inability to retrieve an already-consumed streaming body through CDP; the test now captures a cloned browser Fetch response. A later assertion needed to accept both FastAPI and Fast API spelling.
- Final real public Chromium test: 1 passed (30.3s total, 28.7s test), asking the user's exact 'whta is fast api' through the Docker app and existing Ollama. Verified a visible answer, no display crash, no reasoning section/text in the default response, 1024 default, and final done_reason=stop rather than length. Temporary authenticated test account removed. Screenshot: test-results/fastapi-public.png.

This confirms complete final-answer delivery for the tested question. Longer questions/responses can still require selecting 2048 output tokens. The installed model continues to reason internally; Show thinking controls visibility, not disabling computation for these weights.
