# Local Qwen fallback selection

The fallback behind `llama-safe.service` should be a **Qwen-family GGUF**, not a generic Llama model. On an 8 GB Jetson Orin Nano, model choice is a measured deployment decision because weights, KV cache, CUDA buffers, the OS, and the ConglomerAIte process all share LPDDR memory.

## Starting candidate

Hugging Face model search on 2026-07-18 surfaced [`unsloth/Qwen3.5-4B-GGUF`](https://huggingface.co/unsloth/Qwen3.5-4B-GGUF) as a current small Qwen GGUF candidate. Start with a Q4-class quantization, one llama.cpp slot, a conservative context, and bounded output. If measured headroom is inadequate, reduce quantization/context or test a smaller Qwen-family instruct model. This is a benchmark candidate—not a guarantee that every build, JetPack release, or context size fits.

For a reproducible demo:

1. Download the selected artifact during a maintenance window, never from the runtime service.
2. Pin the repository revision and exact filename in the deployment inventory.
3. Record the SHA-256 checksum, llama.cpp build/commit, JetPack version, context size, GPU layers, and idle/peak memory.
4. Keep the model outside the application release directory so `rsync` cannot delete or recopy multi-gigabyte weights.
5. Bind the local OpenAI-compatible endpoint to `127.0.0.1:8080` and expose no unauthenticated LAN listener.

## Acceptance test

Accept a model/configuration only after the Nano completes the representative task corpus in MAX-N mode with:

- no cgroup OOM or kernel OOM events;
- sufficient `MemAvailable` and cgroup headroom at peak generation;
- bounded p95 latency and no sustained swap thrashing;
- successful cloud-to-local handoff without losing the current candidate/critique;
- a clean service recovery after an intentionally stopped local inference process.

NVMe swap is a last-resort cushion, not additional GPU memory. Never use a successful swapped run as proof that a larger model is production-safe.
