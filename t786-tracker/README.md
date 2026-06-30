# T786 Bus Tracker

Tracks the RapidKL T786 bus (LRT Asia Jaya ↺ MRT Phileo Damansara, passing
Jaya One) using Malaysia's official open GTFS-Realtime feed
(https://developer.data.gov.my/realtime-api/gtfs-realtime), polling every
2 minutes during service hours (06:00–23:30 MYT) and logging every observed
position relative to the "Jaya One Mall (Opp)" stop into `data/t786_history.csv`.

## What this gives you

- A week (or more — it just keeps accumulating) of raw observations: for
  every poll, which T786 vehicles were running, how many stops away from
  Jaya One (Opp) they were, and the straight-line distance in metres.
- From this you can derive: actual headway (gap between consecutive buses
  passing the stop), how consistent the frequency is by time of day, and
  whether the 2:15–2:45pm window is reliably served.

## One-time setup (~10 minutes)

1. Create a free GitHub account if you don't have one: https://github.com/join
2. Create a **new repository** (can be public — public repos get unlimited
   free Actions minutes, which matters since this polls ~500 times/day).
   - If you'd rather keep it private, that's fine too, just keep an eye on
     your Actions usage quota (Settings → Billing).
3. Upload all the files in this folder to that repository, preserving the
   folder structure (`.github/workflows/track.yml` must stay at that exact
   path for GitHub to recognize it as a scheduled workflow).
   - Easiest way: on the repo page, click "Add file" → "Upload files", drag
     the whole folder in, commit.
4. Go to the repo's **Actions** tab. You should see a workflow called
   "Track T786 Bus". Click into it and hit **"Run workflow"** once manually
   to test that it works (don't wait for the schedule).
   - Check the run's logs. You should see lines like
     `Logged 1 T786 vehicle observation(s).`
   - If it fails, the error log will usually point at either a stale GTFS
     static schema (route/stop names sometimes change) or a temporary API
     outage — see Troubleshooting below.
5. If the test run succeeds, leave it — it'll now run automatically every
   2 minutes from 6am to 11:30pm Malaysia time, every day, appending to
   `data/t786_history.csv` in your repo.

## Viewing your data

Open the dashboard artifact (provided separately) and point it at your
repo's raw CSV URL, which will look like:

```
https://raw.githubusercontent.com/<your-username>/<your-repo>/main/data/t786_history.csv
```

The dashboard reads this directly — no need to download anything manually.

## Troubleshooting

- **No rows ever appear**: check the Actions tab for run logs. A common
  cause is the static GTFS feed temporarily not listing T786 (route renumbers
  do happen) — the script will print a clear WARNING if so.
- **Gaps in the data**: GitHub's free-tier cron scheduler can delay runs by
  a few minutes during high load periods. This is normal and won't ruin
  the dataset, just adds occasional small gaps.
- **Stopped after a few days**: if your repo is private and you hit the
  Actions free-tier minute quota, switch the repo to public or upgrade.
