# CoC Base Analyzer — Data Pipeline

Phase 1a: link harvesting from YouTube and community layout sites.

## Setup

```bash
cd data-pipeline
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# Fill in API keys in .env
```

## Usage (Phase 1a)

```python
from harvesters.youtube_harvester import YouTubeHarvester
from harvesters.site_harvester import SiteHarvester
from harvesters.base_registry import BaseRegistry

registry = BaseRegistry("data/base_links.jsonl")

# YouTube (requires YOUTUBE_API_KEY)
yt = YouTubeHarvester(registry=registry)
yt.harvest(max_results_per_query=10)

# Community sites (respects robots.txt)
site = SiteHarvester(registry=registry)
await site.harvest(["https://clashofclanslayouts.org/"])
```

See `docs/DATA_STRATEGY.md` for crawling policy and link decoding roadmap.
