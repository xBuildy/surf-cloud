# Wave Search — SearXNG + MeiliSearch for Wave OS

## SearXNG (Web Search)
Self-hosted metasearch engine aggregating 70+ search engines.
- JSON API at /search?q={query}&format=json
- Custom Wave OS dark theme
- Deployed at wave-search-production.up.railway.app

## MeiliSearch (Internal Search)
Lightning-fast full-text search for Wave OS entities.
- REST API, typo-tolerant, <50ms results
- Indexes: Pipelines, KnowledgeBase, Files, Notes, ChatMessages, CalendarEvents
- Powers the global Cmd+K search bar in Wave OS
- Deployed at wave-meili-search-production.up.railway.app

## Deployment
1. Set Railway service root to `wave-search/` for SearXNG
2. Set Railway service root to `wave-search/meili/` for MeiliSearch
3. SearXNG: expose port 8080, no env vars needed
4. MeiliSearch: expose port 7700, set MEILI_MASTER_KEY
