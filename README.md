# Peer Based Mixing for Decentralized Federated Learning

Peer-based decentralized federated learning (DFL) over a stateless mixnet, with full control via FastAPI and a React
frontend.

Each peer trains a local PyTorch model and exchanges updates with its neighbours through a Sphinx-format mixnet running
over QUIC with mutual TLS. There is no central aggregator — peers aggregate whatever they receive, either with FedAvg or
with Krum when you want some Byzantine resilience. Inline acknowledgments and message tracking keep the exchange
reliable on top of the mixnet's cover traffic and shuffling. Every peer runs as its own Docker container; the FastAPI
backend launches and orchestrates them, and the React dashboard streams live metrics while a run is going.

It's built on FastAPI (served by Uvicorn) for the async backend, React for the dashboard, Docker to isolate each peer,
PyTorch for the models (LeNet-5, SqueezeNet, MobileNetV2), and the [SphinxMix](https://sphinxmix.readthedocs.io/en/latest/)
library for the packet format.

## Quickstart

### 1. Clone the repository

```bash
git clone https://github.com/Altishofer/MixDfl.git
cd MixDfl
```

### 2. Build the Docker image for nodes

Install Docker: https://docs.docker.com/engine/install/ubuntu/#install-using-the-repository

Install build dependencies:

```bash
sudo apt install libssl-dev libffi-dev
```

```bash
docker build -t dfl_node ./node
```

*or for debugging purposes*

```bash
docker build -t dfl_node ./node --progress=plain --no-cache
```

### 3. Install Python 3.14

```bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install python3.14 python3.14-venv python3.14-dev
```

### 4. Create a new venv

```bash
python3.14 -m venv .venv
source .venv/bin/activate
```

### 5. Install Python requirements

```bash
pip install --upgrade pip
pip install -r requirements.txt
pip install -r ./node/requirements.txt
```

### 6. Start the FastAPI backend

```bash
uvicorn manager.app:app --host 127.0.0.1 --port 8000 --timeout-keep-alive 60
```

Backend listens on `http://127.0.0.1:8000`. The React frontend and the experiment runners reach it directly over HTTP.

### 7. Install Node.js and set up the React frontend

```bash
sudo apt install npm
npm install --prefix frontend
```

### 8. Start the React frontend

```bash
npm start --prefix frontend
```

Frontend runs at [http://localhost:3001](http://localhost:3001).

## Configuration

A run is described by an experiment config. The frontend exposes these as form fields; the same fields can be sent as
JSON to the API (see below). Defaults live in `manager/models/config_models.py`.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `model_name` | `lenet5` | Neural network architecture |
| `dataset` | `mnist` | Training dataset |
| `n_nodes` | `10` | Number of peers (1–100) |
| `n_rounds` | `10` | Training rounds (1–100) |
| `batch_size` | `64` | Local batch size (16–256) |
| `dirichlet_alpha` | `10.0` | Data heterogeneity (lower is more skewed) |
| `graph_degree` | `4` | Node degree of the circulant topology |
| `max_hops` | `2` | Max mixnet routing hops |
| `mix_enabled` | `true` | Enable mixing |
| `mix_mu` | `0.1` | Send interval in seconds |
| `mix_outbox_size` | `10` | Shuffle queue size per mixing step |
| `aggregation_algorithm` | `fedavg` | `fedavg` or `krum` |
| `quantization_bits` | `8` | Quantization bit width (`8` or `32`) |

## Running a Simulation

With the backend and frontend both running:

1. Open the dashboard at [http://localhost:3001](http://localhost:3001).
2. Set the run parameters (peers, rounds, dataset, topology, mixing) in the control panel.
3. Start the run. The manager launches one Docker container per peer, named `node_0 … node_{N-1}`, each training on its
   own data partition and exchanging model updates through the mixnet.
4. Watch live metrics stream into the dashboard over SSE (communication, model exchange, mixnet, learning, resources).
5. Stop the run when it finishes, then export the collected metrics to CSV.

The dashboard drives the same HTTP API directly, so a run can also be controlled from the command line:

```bash
# start a run with a custom config
curl -X POST http://127.0.0.1:8000/nodes/start \
  -H "Content-Type: application/json" \
  -d '{"n_nodes": 10, "n_rounds": 10, "dataset": "mnist", "graph_degree": 4}'

# node statuses
curl http://127.0.0.1:8000/nodes/status

# stop all node containers
curl -X POST http://127.0.0.1:8000/nodes/stop

# save the current metrics to a CSV under metrics/ and clear the buffer
curl http://127.0.0.1:8000/metrics/clear
```

Collected time-series land as CSV files under `metrics/`.

## Useful Commands

```bash
# rebuild the node image after changing node/Dockerfile or node/requirements.txt
docker build -t dfl_node ./node

# rebuild from scratch with full build output
docker build -t dfl_node ./node --progress=plain --no-cache

# list any running peer containers
docker ps --filter "name=node_"

# force-remove stray peer containers from an interrupted run
docker rm -f $(docker ps -aq --filter "name=node_")

# follow one peer's logs
docker logs -f node_0

# leave the Python virtual environment
deactivate
```

The `node/` directory is mounted into each container, so node-side code changes take effect on the next run without
rebuilding the image. Rebuild only after editing `node/Dockerfile` or `node/requirements.txt`.

## Project Structure

```bash
MixDfl/
├── node/               # Dockerized peer node (Python)
│   ├── learning/       # FL training, aggregation, data partitioning
│   ├── communication/  # Sphinx routing, QUIC transport, mixing
│   ├── metrics/        # per-node metric collection
│   └── utils/          # Config, logging, decorators
├── manager/            # FastAPI backend for orchestration
│   ├── controllers/    # HTTP endpoints
│   ├── services/       # Business logic (nodes, metrics, topology)
│   ├── models/         # Pydantic schemas and config models
│   └── utils/          # Docker and certificate utilities
├── frontend/           # React dashboard
├── experiments/        # Jupyter notebooks for analysis
├── metrics/            # Generated CSV time-series files
└── secrets/            # PKI keys and TLS certs (auto-generated)
```
