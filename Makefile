# Local shortcuts. CI calls the same commands directly (.github/workflows), so nothing here is required.
# Run `make help` for the list.
#
# Settings: put PROFILE (your Databricks CLI profile) and VARS (bundle variables) in local.mk, which is not
# committed: cp local.mk.example local.mk. Or pass them per command: make pull PROFILE=my-dev

-include local.mk

TARGET  ?= dev
PROFILE ?=
VARS    ?=
VENV    ?= .venv
PY      := $(VENV)/bin/python

ifneq ($(PROFILE),)
export DATABRICKS_CONFIG_PROFILE := $(PROFILE)
endif

.DEFAULT_GOAL := help
.PHONY: help setup test validate plan deploy seed gate pull clean check-auth

help: ## Show the available commands
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-10s %s\n", $$1, $$2}'
	@echo ""
	@echo "  Options: TARGET=dev|staging|prod (default dev), PROFILE=<cli profile>, VARS=\"--var name=value\""

setup: $(VENV)/.installed ## Create .venv and install the Python requirements
	@echo "Python environment ready: $(VENV)"

$(VENV)/.installed: requirements.txt requirements-dev.txt
	python3 -m venv $(VENV)
	$(PY) -m pip install --quiet --upgrade pip
	$(PY) -m pip install --quiet -r requirements-dev.txt
	@touch $@

test: setup ## Run the unit tests
	$(PY) -m pytest -q

# Stop with a clear message instead of falling back to the DEFAULT CLI profile.
check-auth:
	@if [ -z "$(PROFILE)$(DATABRICKS_CONFIG_PROFILE)$(DATABRICKS_HOST)" ]; then \
	  echo "No Databricks profile set. Add PROFILE=<name> to local.mk (cp local.mk.example local.mk) or run make $(MAKECMDGOALS) PROFILE=<name>."; \
	  echo "Sign in first with: databricks auth login --profile <name>"; exit 1; fi

validate: check-auth ## Validate the bundle for TARGET
	databricks bundle validate -t $(TARGET) $(VARS)

plan: check-auth ## Show what a deployment to TARGET would change
	databricks bundle plan -t $(TARGET) $(VARS)

deploy: check-auth ## Deploy the agent, its benchmarks and the gate job to TARGET
	databricks bundle deploy -t $(TARGET) $(VARS)

seed: check-auth setup ## Example only: create the sample sales tables in TARGET's catalog
	$(PY) scripts/seed_demo_data.py --target $(TARGET) $(subst --var ,--var=,$(VARS))

gate: check-auth ## Run the benchmarks on TARGET; fails when accuracy is not above the threshold
	scripts/run_gate.sh $(TARGET) $(VARS)

pull: check-auth setup ## Pull edits made in the Genie UI on TARGET's agent back into its resource file
	$(PY) scripts/pull_agent.py --target $(TARGET) $(subst --var ,--var=,$(VARS)) $(if $(OUT),--out $(OUT)) $(if $(SPACE_ID),--space-id $(SPACE_ID))

clean: ## Remove .venv
	rm -rf $(VENV)
