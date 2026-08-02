/**
 * One-time YouTube authorisation: turns a Google OAuth client into the
 * refresh token the uploader needs.
 *
 *     npm run authorize            (from apps/uploader)
 *
 * You consent in your own browser and the token is printed here; nothing in
 * this repo ever sees your Google password. The token is long-lived, so this
 * is run once and then forgotten — unless the channel's password changes, the
 * token is revoked, or the OAuth app sits in "Testing" mode, where Google
 * expires refresh tokens after seven days. Publishing the app (even without
 * verification, for personal use) is what makes a daily channel stop needing
 * re-authorisation every week.
 *
 * Prerequisites, done once in the Google Cloud console by you:
 *   1. Create a project, enable "YouTube Data API v3".
 *   2. Configure the OAuth consent screen; add yourself as a test user.
 *   3. Create an OAuth client ID of type "Desktop app".
 *   4. Put its id and secret in .env as GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET.
 */

import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { URL } from 'node:url';
import dotenv from 'dotenv';
import { google } from 'googleapis';

// The repo's .env lives at the root, but npm runs this with apps/uploader as
// the working directory and `dotenv/config` only looks there. That reported
// "set GOOGLE_CLIENT_ID first" on a machine where it had been set all along —
// a maddening thing to be told, and the reason this is explicit now.
const ENV_PATH = path.resolve(process.cwd(), '..', '..', '.env');
dotenv.config({ path: ENV_PATH });

// Upload plus the read access the uploader uses to list recent videos for the
// "More videos" block. Nothing broader: this token should not be able to
// delete anything.
const SCOPES = [
  'https://www.googleapis.com/auth/youtube.upload',
  'https://www.googleapis.com/auth/youtube.readonly',
  // captions.insert is not covered by youtube.upload. force-ssl is the only
  // scope that grants it, and it is broader than the rest — it can also
  // delete. Requested because uploading our own subtitle track is worth it:
  // YouTube's transcription mangles square names, and this render says one 83
  // times. Nothing in the daily path calls delete.
  'https://www.googleapis.com/auth/youtube.force-ssl',
];

const PORT = 8790;
const REDIRECT = `http://localhost:${PORT}/oauth2callback`;

async function main(): Promise<number> {
  const clientId = process.env.GOOGLE_CLIENT_ID;
  const clientSecret = process.env.GOOGLE_CLIENT_SECRET;
  if (!clientId || !clientSecret) {
    console.error(
      'Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env first.\n' +
        'Create them at https://console.cloud.google.com/apis/credentials\n' +
        'as an OAuth client ID of type "Desktop app", with the YouTube Data\n' +
        'API v3 enabled for the project.'
    );
    return 2;
  }

  const oauth2Client = new google.auth.OAuth2(clientId, clientSecret, REDIRECT);
  const authUrl = oauth2Client.generateAuthUrl({
    access_type: 'offline',
    scope: SCOPES,
    // Without this, Google returns a refresh token only on the very first
    // consent ever given to this client — re-running the script would then
    // print an access token and no refresh token, which fails silently a
    // week later.
    prompt: 'consent',
  });

  console.log('\nOpen this URL, sign in as the channel owner, and approve:\n');
  console.log(authUrl);
  console.log(`\nWaiting for the redirect back to ${REDIRECT} …\n`);

  const code: string = await new Promise((resolve, reject) => {
    const server = http.createServer((req, res) => {
      if (!req.url?.startsWith('/oauth2callback')) {
        res.writeHead(404).end();
        return;
      }
      const params = new URL(req.url, `http://localhost:${PORT}`).searchParams;
      const err = params.get('error');
      const got = params.get('code');
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      res.end(
        `<body style="font:16px system-ui;padding:3rem;background:#0b0f14;color:#e6edf3">` +
          (err
            ? `<h2>Authorisation refused</h2><p>${err}</p>`
            : `<h2>Authorised</h2><p>You can close this tab and return to the terminal.</p>`) +
          `</body>`
      );
      server.close();
      if (err || !got) reject(new Error(err ?? 'no code returned'));
      else resolve(got);
    });
    server.listen(PORT);
    server.on('error', reject);
  });

  const { tokens } = await oauth2Client.getToken(code);
  if (!tokens.refresh_token) {
    console.error(
      '\nGoogle returned no refresh token. That happens when this client has\n' +
        'been authorised before. Revoke it at\n' +
        'https://myaccount.google.com/permissions and run this again.'
    );
    return 1;
  }

  // Written straight into .env rather than printed. A refresh token is a
  // standing credential for the channel; echoing it to a terminal leaves it
  // in scrollback and in any log that happens to be capturing stdout.
  const envPath = ENV_PATH;
  try {
    const existing = fs.existsSync(envPath) ? fs.readFileSync(envPath, 'utf-8') : '';
    const line = `GOOGLE_REFRESH_TOKEN=${tokens.refresh_token}`;
    const next = /^GOOGLE_REFRESH_TOKEN=.*$/m.test(existing)
      ? existing.replace(/^GOOGLE_REFRESH_TOKEN=.*$/m, line)
      : existing.replace(/\s*$/, '\n') + line + '\n';
    fs.writeFileSync(envPath, next, 'utf-8');
    console.log(`\nAuthorised. Refresh token written to ${envPath}\n`);
  } catch (e) {
    console.error('\nAuthorised, but .env could not be written:', e);
    console.error('Add the refresh token by hand — it is:');
    console.error(`GOOGLE_REFRESH_TOKEN=${tokens.refresh_token}\n`);
  }
  console.log('Now check it works without publishing anything:');
  console.log('  python services/orchestrator/flow.py --dry-run-upload\n');
  return 0;
}

main().then((c) => process.exit(c)).catch((e) => {
  console.error(e instanceof Error ? e.message : e);
  process.exit(1);
});
