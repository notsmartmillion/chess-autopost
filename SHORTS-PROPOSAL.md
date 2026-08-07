# Proposal — vertical Shorts from the existing beat pipeline

Status: **proposal, not built.** Written 2026-08-07.

Recommendation in one line: add a 9:16 composition and publish Shorts to the
**same channel**, but clear the upload backlog first — the bottleneck today is
shipping, not producing.

---

## Why this repo is unusually well-suited to it

The hard problem in automated short-form is *selection*: which 30 seconds of a
40-minute game is worth clipping. This pipeline already answers that as a
byproduct of analysis.

- `facts.py` emits a **ranked `keyMoments` list** with numeric weights
  (`brilliant: 9.0`, `blunder: 8.0`). That is a clip-selection function.
- Beats carry an explicit `fen`, `durationMs`, and word-level `moveAtMs`. A clip
  has exact in/out points with no re-alignment pass.
- The renderer is Remotion, so a vertical output is **a new `<Composition>` with
  re-laid-out components** — not a second pipeline. Audio, timings, board
  animation, and the whole director stage are reused unchanged.
- `apps/uploader/metadata.ts` already derives `#BrilliantMove` / `#Blunder`
  hashtags from beat tags.

The marginal cost is a layout and a selector. Almost everything else exists.

---

## Do this first: 10 videos are built and unpublished

`state/published.json` currently holds 13 entries — **3 `uploaded`, 10
`not_uploaded`.** Adding a second output format to a pipeline that isn't
shipping its first one is solving the wrong problem.

Check, in order:

1. `have_upload_creds()` in `services/orchestrator/flow.py:395` — is
   `GOOGLE_REFRESH_TOKEN` present and unexpired?
2. Whether the daily run is invoked with `--no-upload`.
3. `outputs/upload_result.json` from the last attempted run.

Get the daily run publishing reliably, then Shorts multiplies something that
works instead of doubling something stalled.

---

## Same channel, not a separate Shorts channel

**Post to the same channel.** YouTube has stated publicly that mixing Shorts and
long-form on one channel does not harm channel performance, and the two run on
largely separate recommendation systems — Shorts-feed discovery does not draw on
long-form ranking signals. Channels running both tend to grow faster than
channels running either alone.

The old subscriber-dilution worry is now mostly overblown, but there is a real
caveat that shapes the design below: **Shorts only help if they act as a funnel,
not as filler.** Low-effort Shorts posted to stay active are a vote against the
channel. What the Shorts feed rewards is completion rate above ~50%, looping,
and clicks through to long-form.

A separate Shorts channel would cost you the one thing that makes this worth
doing — the pipe from a 45-second brilliancy to the full game analysis on the
same channel — and would double the upload credentials, branding, and
maintenance surface for no benefit.

**So: same channel, deliberately built as a funnel.** Every Short ends pointing
at the full game.

---

## Composition spec

New entry in `apps/renderer/src/index.tsx`:

```tsx
<Composition
  id="ChessShort"
  component={ChessShort}
  fps={FPS}
  width={1080}
  height={1920}
  calculateMetadata={calculateShortMetadata}
/>
```

Layout, top to bottom:

| Band | Height | Contents |
|---|---|---|
| Hook | ~180px | One line: "White to play. Find the win." / "Tal just hung his queen." |
| Board | 1080px | `AnimatedBoard` at full width — square, so it fills edge to edge |
| Rail | ~450px | Collapsed `AnalysisRail`: players, eval readout, move + quality badge |
| CTA | ~210px | "Full game on the channel" + game title |

Reuse `THEME` from `apps/renderer/src/components/AnalysisRail.tsx` and keep it in
sync with `COLOR_*` in `director.py`, exactly as the landscape composition does.

The board is the whole point of the format — give it the full 1080 width and let
the rail collapse to a strip. Do not try to port the landscape side-rail layout.

---

## Clip selection

A Short is: **the highest-scoring `keyMoment`, its surrounding beats, and the
variation that refutes it.**

```
1. Take keyMoments[0] (already ranked by facts.py).
2. Window = the beat containing that move, minus 1 beat of setup,
   plus any beats with branch=true that immediately follow it.
3. Clamp to <= 60s of summed durationMs. If it overflows, drop setup beats
   before dropping the variation — the refutation is the payoff.
4. Prepend a generated hook beat; append a CTA beat.
```

Target **under 60 seconds.** Shorts now allow up to 3 minutes, but sub-60s
remains the most reliable threshold for consistent Shorts treatment across
surfaces, and completion rate is the metric that matters most.

A brilliancy or a blunder with a clean refutation is the strongest cut. Games
whose top `keyMoment` scores below ~7.0 probably shouldn't produce a Short at
all — silence beats filler here, per the funnel caveat above.

---

## Upload path

No new integration. Shorts use the **same `videos.insert` endpoint** as
long-form, so `apps/uploader` works as-is: same OAuth client, same
`GOOGLE_REFRESH_TOKEN`, same channel. Classification is automatic from duration
+ aspect ratio; `#Shorts` in the title or description is the supporting
programmatic signal.

⚠️ **Quota is the real constraint.** Each `videos.insert` costs **1,600 units**
against a default **10,000/day** — about **6 uploads per day total**, long-form
included. A daily long-form plus a handful of Shorts fits; a "clip every key
moment" strategy does not. Budget it explicitly in `flow.py`, or request a quota
increase before scaling up.

Metadata changes needed in `apps/uploader/metadata.ts`:

- A separate title template — hook-style, not `Player vs Player, Event Year`.
- `#Shorts` appended to the tag list.
- Description leads with the link to the full-game video, not the channel links.

---

## Gotchas

- **Do not remount the board.** Same rule as the landscape composition: mount
  `AnimatedBoard` once and drive it from the current beat. Remounting per beat
  recreates all 32 sprites and the pieces visibly flicker.
- **Piece sprites must use Remotion's `<Img>`**, not `<img>` — Remotion only
  waits for `<Img>` before capturing a frame.
- **Re-run TTS for the clip; do not slice the long-form audio.** The hook and
  CTA beats are new text, and word timings must come from the same pass or
  `moveAtMs` will drift against the board.
- **Thumbnails don't apply.** The Shorts feed uses the first frame — make frame
  0 the hook card with the board already in position, not a fade-in.
- **`used_games.json` dedupe.** Decide whether a game that produced a Short is
  "used". Recommended: no — track Shorts separately so a game can yield both.

---

## What NOT to do

**Do not cross-post links to Facebook, Instagram, or Threads.** The sibling
projects have measured this: the ETG Facebook page has 1 follower and no
meaningful reach after months of posting; Threads down-ranks posts carrying
outbound links; Instagram doesn't render links in captions at all. Posting
"new video 🔗" to accounts with no audience converts nothing and adds a
compliance surface for zero return.

If Shorts prove out on YouTube, the natural next step is **Reels and TikTok with
the same vertical asset** — not link posts. That needs video publishing built in
`socials_bot`, which today handles text and photo only (Reels is a different
container flow: `media_type: REELS`, `video_url`, much longer processing polls).

Sequencing: fix uploads → ship Shorts to YouTube → prove the format earns views
→ then consider other vertical surfaces.

---

## Sources

- [YouTube Shorts upload requirements 2026](https://www.shortsync.app/resources/youtube-shorts-upload-requirements-2026)
- [YouTube upload API: videos & Shorts](https://postproxy.dev/blog/youtube-upload-api-guide/)
- [Shorts and long-form on the same channel](https://www.pandavideo.com/blog/shorts-and-long-form-videos-same-channel)
- [YouTube algorithm updates 2026](https://outlierkit.com/resources/youtube-algorithm-updates/)
