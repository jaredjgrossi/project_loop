# Reach the Mac from the iPhone over Tailscale (Phase 3, step 6)

Tailscale puts the Mac and the iPhone on one private network, the "tailnet". `tailscale serve` gives the Mac an
HTTPS address on it, `https://<mac-name>.<tailnet>.ts.net`, with a real certificate. iOS accepts that with no
App Transport Security exceptions, and the API itself stays on 127.0.0.1, where nothing outside the Mac can reach it.
Nothing is exposed to the internet: serve isn't Funnel.

## Once
1. **Mac:** in the Mac App Store, search **Tailscale**, click **Get**, then **Open**.
   - Click the Tailscale icon in the menu bar, then **Log in**. Sign in with any account (Google, Apple, GitHub);
     use the same one on the phone.
   - When macOS asks to add a VPN configuration, click **Allow**. If it asks about a system extension, allow it in
     System Settings.
2. **iPhone:** in the App Store, search **Tailscale**, tap **Get**, then open it.
   - Log in with the same account.
   - Tap **Allow** when iOS asks to add a VPN configuration, then confirm with Face ID or your passcode.
   - Make sure the switch at the top shows **Connected**.
3. **Browser on the Mac:** open <https://login.tailscale.com/admin/dns>.
   - If **MagicDNS** shows an **Enable** button, click it.
   - Under **HTTPS Certificates**, click **Enable HTTPS** and confirm.

## Each time
4. **Terminal tab 1**, the API:
   ```bash
   cd ~/Developer/loop/.claude/worktrees/phase3 && caffeinate -i make serve
   ```
   Leave it running. The `phase3` branch isn't merged yet, so run it from this worktree; it reads `~/Developer/loop/.env`.
   `caffeinate -i` keeps the Mac awake while it runs (keep it plugged in; closing the lid still sleeps it).
5. **Terminal tab 2**, the HTTPS address (once; it stays on across restarts until you turn it off):
   ```bash
   /Applications/Tailscale.app/Contents/MacOS/Tailscale serve --bg 8000
   ```
   It prints the address, `https://<mac-name>.<tailnet>.ts.net`. If it prints a link to enable HTTPS, open that
   link, click **Enable**, and run the command again.
6. **iPhone, Safari:** open `https://<mac-name>.<tailnet>.ts.net/v1/health`. You should see `"ok":true`. Send the
   address to the iPhone session: it goes in `ios/Config/Secrets.xcconfig`, which is git-ignored.

## Turn it off
```bash
/Applications/Tailscale.app/Contents/MacOS/Tailscale serve reset
```
Stop the API with Ctrl-C in tab 1.

## If something is off
- **Health page doesn't load:** check that both devices show Connected in Tailscale, and that tab 1 says
  `Uvicorn running on http://127.0.0.1:8000`.
- **`"ok":false`:** the JSON says which part is down. `engine` or `database` false means Docker isn't up
  (`make up`); `parser` false means the Claude key is missing from `.env`.
- **Routes arrive all at once at the end, not streamed:** tell Code. The proxy is meant to pass the stream through
  as it comes.
