# Git Arsenal

AI-powered GitHub repository search engine with 3D galaxy visualization.

Search 150k+ open-source repositories using natural language, explore connections between projects in an interactive 3D star map, and let an AI agent find what you need via MCP tools.

## Features

- **Multi-channel Search** — Three-channel recall (keyword, tree-structure HyDE, wiki embedding) with RRF fusion
- **3D Galaxy** — UMAP-based 3D visualization of repository clusters with Jaccard similarity edges
- **AI Agent Chat** — Conversational interface powered by MCP tools for natural language repo discovery
- **Language Filters** — Toggle visibility by programming language in the galaxy view
- **Cross-cluster Exploration** — Click any node to dynamically load its global neighbors

## Architecture

```
packages/
├── api/          # FastAPI backend — search, galaxy, auth APIs
├── web/          # Next.js frontend — chat, galaxy 3D visualization
└── mcp-server/   # MCP tool server — exposes search to AI agents
```

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 15, React 19, Tailwind CSS, 3d-force-graph |
| Backend | FastAPI, SQLAlchemy, Qdrant (vector DB), PostgreSQL |
| AI | OpenAI-compatible embeddings (text-embedding-v4), GLM for query parsing |
| Agent | MCP (Model Context Protocol) |

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- Docker & Docker Compose (for Qdrant + PostgreSQL)

### 1. Clone & install

```bash
git clone https://github.com/<your-username>/git-arsenal.git
cd git-arsenal

# Backend
cd packages/api && pip install -r requirements.txt && cd ../..

# Frontend
cd packages/web && npm install && cd ../..
```

### 2. Start infrastructure

```bash
docker compose up -d   # Starts Qdrant + PostgreSQL
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env — fill in LLM_API_KEY and EMBED_API_KEY
```

### 4. Ingest data & run

The repo ships with a **dev dataset** (~1,200 repos, 31 MB) for quick onboarding.
The default `DATA_PROFILE=dev` uses it automatically:

```bash
# Initialize database
python scripts/init_db.py

# Ingest data into Qdrant (defaults to packages/api/data/dev/)
python scripts/ingest.py --force

# Start backend
cd packages/api && uvicorn server:app --host 0.0.0.0 --port 8003 &

# Start frontend
cd packages/web && npm run dev
```

Open http://localhost:3000.

## Data Profiles

The project supports multiple data profiles via the `DATA_PROFILE` environment variable:

| Profile | Repos | Size | Description |
|---------|------:|-----:|-------------|
| `dev` | 1,178 | 31 MB | Bundled in git. 10 dense clusters (3D Graphics, Mobile/Kotlin, Computer Vision). Good for development and testing. |
| `product` | 81,655 | 3.0 GB | 200+ star repos. Full production dataset. Download separately. |
| `bak` | 151,209 | 5.0 GB | 100+ star repos. Legacy backup. |

### Switching profiles

```bash
# In .env
DATA_PROFILE=product   # or dev, bak

# Or override directly
DATA_DIR=/path/to/custom/data
```

Each profile directory contains the same 8 files:

| File | Description |
|------|-------------|
| `repos_meta.jsonl` | Repository metadata (one JSON per line: full_name, stars, language, description, tree_text, wiki_text, html_url) |
| `embeddings.npy` | Tree structure embeddings (N × 1024, float32) |
| `wiki_embeddings.npy` | Wiki text embeddings (N × 1024, float32) |
| `wiki_texts.jsonl` | Wiki text content (one JSON per line) |
| `galaxy_edges.npz` | Jaccard similarity edges (src, dst, sim arrays) |
| `positions_3d.npy` | UMAP 3D coordinates (N × 3, float32) |
| `cluster_tree.json` | Hierarchical cluster tree (bisecting KMeans) |
| `repo_leaf_labels.npy` | Per-repo leaf cluster assignment (N, int32) |

### Setting up production data

```bash
# 1. Place production data files in packages/api/data/product/
#    (download link or generation instructions TBD)

# 2. Ingest into Qdrant
python scripts/ingest.py --data-dir packages/api/data/product --force

# 3. Switch profile
echo "DATA_PROFILE=product" >> .env

# 4. Restart the API server
```

### Regenerating data from scratch

```bash
# Step 1: Collect repos (requires GitHub API)
# Step 2: Generate embeddings
python scripts/embed_wiki.py

# Step 3: Run galaxy preprocessing (clustering + UMAP + edges)
python scripts/preprocess_galaxy_200star.py

# Step 4: Ingest into Qdrant
python scripts/ingest.py --data-dir packages/api/data/product --force
```

## MCP Integration

Git Arsenal exposes an MCP server for AI agents (Cursor, Claude Desktop, etc.):

```json
{
  "mcpServers": {
    "git-arsenal": {
      "type": "stdio",
      "command": "node",
      "args": ["packages/mcp-server/index.js"],
      "env": {
        "ARSENAL_API_URL": "http://localhost:8003"
      }
    }
  }
}
```

## License

MIT
