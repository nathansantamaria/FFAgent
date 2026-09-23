# Published dashboard

Served by GitHub Pages at https://nathansantamaria.github.io/FFAgent/

**This is an https origin, so tier-1 live fetching works** — the page talks to
api.sleeper.app directly and shows data as of the second you load it, not
whenever the scheduled Action last ran.

To refresh the published copy after a rebuild:

```
python build_dash.py
copy dashboard.html docs\index.html
git add -A && git commit -m "refresh dashboard" && git push
```

Pages redeploys about a minute after the push.
