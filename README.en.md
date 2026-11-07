# Air Alerts Stats

> English summary. The full documentation of this repository is in Ukrainian: [README.md](README.md).

How many air raids were there on any past day in any Ukrainian district, and how long did they last? The public API cannot answer that: it looks only one month back and allows 2 requests per minute. So the service keeps its own history.

What was built:
- every poll is stored in SQLite, so statistics for any date survive the source's retention window;
- three interchangeable sources behind one env var — keyed full-granularity, a keyless mirror of the official DSNS feed (1606 regions), and a coarse 25-region feed; the switch script validates the new token once and changes nothing if it fails, so the collector never loops on restarts;
- swapping sources duplicates ids, so counts are cleaned with one exact SQL statement; total duration is a union of intervals, not a sum of alerts;
- red (missiles/ballistic) and yellow (drones) alert levels stored separately;
- ops: token read into a 600-perm .env without touching shell history, consistent VACUUM INTO backups under WAL, 429s skipped instead of crashing the collector, honest "unknown" gaps.

Stack: FastAPI, SQLite (WAL), Docker Compose, vanilla JS, bash.
