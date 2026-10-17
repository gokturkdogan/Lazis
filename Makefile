# LAZIS developer commands. `make help` lists them.
# Requires: uv, pnpm (Node 24+), Rust (rustup, stable >= 1.90), Xcode Command Line Tools.

CORE    := core
DESKTOP := apps/desktop
TAURI   := $(DESKTOP)/src-tauri

.DEFAULT_GOAL := help
.PHONY: help setup dev build check test test-core test-ui test-ui-integration test-shell \
        test-keychain lint lint-core lint-ui lint-shell api-schema audit spike-storage clean \
        ollama-agent model-pull bench eval blind test-ollama

help: ## List commands
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-22s %s\n", $$1, $$2}'

setup: ## Install all dependencies (Python venv, Node modules, Rust crates)
	cd $(CORE) && uv sync
	cd $(DESKTOP) && pnpm install --frozen-lockfile
	cd $(TAURI) && cargo fetch

dev: ## Run the desktop app in development (dev profile, Vite hot reload)
	cd $(DESKTOP) && pnpm tauri dev

build: ## Build the release LAZIS.app bundle
	cd $(DESKTOP) && pnpm tauri build

check: lint test ## Lint everything and run every automated test

test: test-core test-ui test-ui-integration test-shell ## Run all automated tests

test-core: ## Backend tests (pytest: unit, integration, security)
	cd $(CORE) && uv run pytest -q

test-ui: ## Frontend unit tests (Vitest)
	cd $(DESKTOP) && pnpm test

test-ui-integration: ## Frontend client against a real backend process
	cd $(DESKTOP) && pnpm test:integration

test-shell: ## Rust shell unit + lifecycle tests (real backend, in-memory key store)
	cd $(TAURI) && cargo test

test-ollama: ## Opt-in: real backend + real Ollama + installed model (LAZIS_TEST_MODEL=...)
	cd $(CORE) && uv run pytest -q -m ollama tests/integration/test_live_ollama.py

test-keychain: ## Opt-in: round-trip a dedicated test item in the real login Keychain
	cd $(TAURI) && cargo test --lib -- --ignored keychain

lint: lint-core lint-ui lint-shell ## All static checks

lint-core: ## ruff, ruff format, pyright (strict), import-linter
	cd $(CORE) && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run lint-imports

lint-ui: ## vue-tsc type check
	cd $(DESKTOP) && pnpm typecheck

lint-shell: ## rustfmt + clippy (warnings are errors)
	cd $(TAURI) && cargo fmt --check && cargo clippy --all-targets -- -D warnings

api-schema: ## Regenerate the OpenAPI snapshot and TypeScript types after API changes
	cd $(CORE) && uv run python -m lazis openapi > ../$(DESKTOP)/ui/src/api/openapi.json
	cd $(DESKTOP) && pnpm gen:api

audit: ## Dependency vulnerability audits (sends package names/versions to advisory services)
	cd $(CORE) && uv run pip-audit --skip-editable
	cd $(DESKTOP) && pnpm audit
	cd $(TAURI) && cargo audit

spike-storage: ## SPK-04/05: SQLCipher + sqlite-vec + FTS5 benchmark (synthetic data)
	cd $(CORE) && uv sync --group spike && uv run python spikes/spk05_storage.py

ollama-agent: ## Run Ollama as a LaunchAgent with cloud features off, loopback only
	scripts/ollama-agent.sh install

model-pull: ## Download one owner-approved model: make model-pull MODEL=qwen3.5:9b-q4_K_M
	scripts/model-pull.sh "$(MODEL)"

bench: ## Phase 2 performance benchmarks: make bench MODEL=... [QUICK=1]
	uv run --project $(CORE) python evals/runners/perf.py --model "$(MODEL)" $(if $(QUICK),--quick,)

eval: ## Phase 2 Turkish quality evaluation: make eval MODEL=...
	uv run --project $(CORE) python evals/runners/quality.py --model "$(MODEL)"

blind: ## Build the blind rating page: make blind MODELS="a b c"
	uv run --project $(CORE) python evals/runners/blind.py build --models $(MODELS)

clean: ## Remove build output (never touches user data or the Keychain)
	rm -rf $(DESKTOP)/ui/dist $(TAURI)/target
