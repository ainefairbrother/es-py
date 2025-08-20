### Description

`es-py` is a ightweight Python toolkit to build IGSR’s Elasticsearch indices from MySQL, replacing the legacy Perl loaders. It supports bulk create and update operations and is compatible with Elasticsearch V8.x. The goal is to keep the new indices functionally equivalent to the old indices while being easier to develop and test.

This repository indexers - one per index type. These do the following: 
1. Query MySQL 
2. Aggregate rows into the document shape expected by the API 
3. Bulk indexes documents into Elasticsearch using either create or update

### Requirements

- Python 3.12+
- Docker (to run a local Elasticsearch instance)
- pyenv (optional, to install Python 3.12)
- uv (optional, fast installer/venv manager) or pip
- ro access to the IGSR MySQL database

### Quickstart (to test or dev locally)

For dev, fork the repo then clone

```bash
git clone git@github.com:<your-username>/es-py.git
cd es-py
```

Run Elasticsearch (single node, security disabled for local dev). See full instructions [here](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/install-elasticsearch-docker-basic).

```bash
# create a dedicated network (only once)
docker network create elastic

# pull a compatible 8.x image (example tag below)
docker pull docker.elastic.co/elasticsearch/elasticsearch:8.13.4

# run ES (single node, security disabled for local dev)
docker run -d --name es01 --net elastic \
  -p 9200:9200 -p 9300:9300 \
  -e "discovery.type=single-node" \
  -e "xpack.security.enabled=false" \
  docker.elastic.co/elasticsearch/elasticsearch:8.13.4

# check it's up
curl http://localhost:9200/
```

Install Python 3.12 using pyenv

```bash
pyenv install 3.12
pyenv local 3.12.11
```

Create and activate virtual environment

```bash
uv venv espy-env
source espy-env/bin/activate

# install es-py deps
uv pip install -r requirements.txt
```

Example build, check and delete of the `population` index

Create `config.ini`

```ini
[database]
host=
port=
user=
password=
name=
```

Then 

```bash
cd es-py

# build (create)
python3 -m index.population_index.indexing \
  --config_file config.ini \
  --es_host http://127.0.0.1:9200/ \
  --type_of create

# quick check
curl -X GET "http://localhost:9200/population/_search" \
  -H 'Content-Type: application/json'

# delete when needed
curl -X DELETE 'http://localhost:9200/population'
```


### Testing

To run the `pytest` unit tests

```bash
cd es-py
pytest -s
```
