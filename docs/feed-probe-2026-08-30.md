# Feed probe - 2026-08-30

Unconditional GET of every registered feed, including disabled ones.
`enabled` in `config/feeds.toml` is set from this, never by hand.

| feed | HTTP | parses | items | newest (h) | ETag | Last-Modified |
|---|---|---|---|---|---|---|
| `cbs_nfl` | 200 | rss | 36 | 1.7 | yes | no |
| `espn_nfl` | 200 | rss | 18 | 1.1 | no | no |
| `fantasypros` | 404 | - | 0 | - | no | no |
| `reddit_ff` | 200 | atom | 25 | 1.4 | no | no |
| `rotowire_articles` | 200 | rss | 5 | 18.5 | no | no |
| `rotowire_news` | 200 | rss | 5 | 23.2 | no | no |
| `yahoo_nfl` | 200 | rss | 50 | 0.4 | no | no |

**Healthy: 6/7**. G3 (>= 2 healthy) PASS.
