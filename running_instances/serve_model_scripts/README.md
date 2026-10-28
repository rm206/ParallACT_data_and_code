# serve_model_scripts

Serve a model with vLLM in docker on a GPU machine. The harness runners reach it
through `running_instances/common/endpoints.py`.

`_prelude.sh` runs `docker run --gpus all … vllm serve` with the script's vLLM image,
mounting `$HF_HOME` (default `~/.cache/huggingface`) so weights download once.
Requires docker with GPU support (NVIDIA Container Toolkit).

| script | model key | HF path | image | parser / reasoning | served name |
|---|---|---|---|---|---|
| `serve_qwen.sh` | qwen | `Qwen/Qwen3.8-Flash-Next-FP8` | `vllm/vllm-openai:nightly` | `qwen3_coder` / `qwen3` | `qwen3-flash-next` |
| `serve_deepseek.sh` | deepseek | `deepseek-ai/DeepSeek-V4-Flash-0731` | `vllm/vllm-openai:v0.28.0` | `deepseek_v4` / `deepseek_v4` | `deepseek-v4-flash` |
| `serve_glm.sh` | glm | `unsloth/GLM-5.3-Flash-FP8` | `vllm/vllm-openai:nightly` | `glm47` / `glm47` | `glm-5.3-flash` |
| `serve_prelim.sh` | (prelim_suggestions) | `Qwen/Qwen3.8-27B-FP8` | `vllm/vllm-openai:nightly` | `qwen3_xml` / `qwen3` | `Qwen/Qwen3.8-27B-FP8` |

## Serve

```bash
bash serve_qwen.sh                         # or serve_deepseek.sh / serve_glm.sh / serve_prelim.sh
PORT=8001 TP=8 MAX_NUM_SEQS=8 bash serve_glm.sh
```

| env | default | meaning |
|---|---|---|
| `PORT` | 8000 | host port |
| `TP` | 4 | tensor-parallel size (number of GPUs) |
| `MAX_NUM_SEQS` | 4 (8 for prelim) | vLLM `--max-num-seqs` |
| `HF_HOME` | `~/.cache/huggingface` | weights cache, mounted into the container |
| `HF_TOKEN` | — | passed through for gated repos |
| `SERVED_NAME` | per script | `--served-model-name` (the runners use the name in `endpoints.py`) |

Wait for `Application startup complete`. The startup log line
`Maximum concurrency for N tokens per request: X.Xx` is the KV-cache ceiling.

## Connect

The runners default to `127.0.0.1:8000` for every model. If the server runs on
another machine, either set `MODEL_HOST=<gpu-host>` or forward the port:

```bash
ssh -N -L 8000:localhost:8000 <user>@<gpu-host>
```

To serve several models at once, give each its own `PORT` and set
`MODEL_PORT_<KEY>` (e.g. `MODEL_PORT_GLM=8001`) for the runners.
