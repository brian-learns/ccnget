REQUIRED_EXECUTABLES = uv rm find

.PHONY: all help check test clean testpackages checkdeps man init mandoc

all: help

help:
	@echo ""
	@echo "  make check      Run ultra-fast static testing pipeline (ruff, bandit, vulture, etc.)"
	@echo "  make test       Run static checks followed immediately by pytest"
	@echo "  make clean      Wipe out test tool cache tracking footprints"
	@echo "  make init       Initialize new project with uv and test setup"
	@echo "  make mandoc     Create man page TODO: make nice python api doc"

check:
	@echo "\n— [An extremely fast Python linter and code formatter](https://docs.astral.sh/ruff/)"
	uv run ruff check src/ --fix
	uv run ruff format src/ --check

	@echo "\n— [AST based security scanner](https://bandit.readthedocs.io/en/latest/)"
	uv run bandit -c pyproject.toml -r src/

	@echo "\n— [Find dead Python code](https://github.com/jendrikseipp/vulture)"
	uv run vulture src/ --min-confidence 80

	@echo "\n— [A tool for refurbishing and modernizing Python codebases](https://github.com/dosisod/refurb)"
	uv run refurb src/

	@echo "\n— [An extremely fast Python type checker and language server]( https://docs.astral.sh/ty/)"
	uv run ty check src/

	@echo "\n— [Interrogate a codebase for docstring coverage](https://interrogate.readthedocs.io/en/latest/)"
	uv run interrogate src/

	@echo "\n— security scan"
	UV_MALWARE_CHECK=1 uv audit --preview-features audit-command --preview-features malware-check


test: check
	uv run pytest -v --durations=5

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache .vulture_cache .uv
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

init: checkdeps pyproject.toml testpackages

checkdeps:
	@$(foreach exec,$(REQUIRED_EXECUTABLES),\
		command -v $(exec) >/dev/null 2>&1 || { echo "Error: $(exec) is required."; exit 1; };)
	@echo "All required commands are available."

testpackages:
	uv add --dev ruff bandit vulture refurb ty pytest interrogate argparse-manpage

#mandoc: man doc
mandoc: man

man:
	mkdir -p man
	uv run argparse-manpage \
		--module ccnget.geturl \
		--function get_parser \
		--prog ccnget \
		--project-name ccnget \
		--version "$$(uv version | awk '{print $$2}')" \
		--include man/__envars.inc \
		> man/ccnget.1


export GIT_CEILING_DIRECTORIES	# can influence `uv init` behaviour
pyproject.toml:
	uv init --package .

dev-cycle-start:
	@echo "--- Validating local Git state for new cycle ---"
	# 1. Reject running directly on main (forces you to make a branch first)
	@CURRENT_BRANCH=$$(git branch --show-current); \
	if [ "$$CURRENT_BRANCH" = "main" ]; then \
		echo "Error: Create a new branch (e.g., 'git checkout -b chore/start-v1.3.0') before running this."; exit 1; \
	fi
	
	# 2. Ensure working directory is completely clean
	@git diff-index --quiet HEAD -- || (echo "Error: Uncommitted changes present!"; exit 1)
	
	# 3. Ensure your local main branch isn't lagging behind GitHub
	@echo "--- Verifying base synchronization ---"
	@git fetch --quiet origin main
	@LOCAL_MAIN=$$(git rev-parse main); REMOTE_MAIN=$$(git rev-parse origin/main); \
	if [ "$$LOCAL_MAIN" != "$$REMOTE_MAIN" ]; then \
		echo "Error: Your local 'main' branch is behind origin/main. Switch to main, pull, and recreate your branch."; exit 1; \
	fi

	@echo "--- Git checks passed. Bumping to dev version ---"
	uv version --bump minor --bump dev
	uv lock --upgrade
	$(MAKE) test
	@echo "Success! Commit these changes to start your new cycle."
	uv version


prerelease: check test
	@echo "--- Performing deep pre-release verification ---"
	@git diff-index --quiet HEAD -- || (echo "Error: Uncommitted changes present!"; exit 1)
	uv lock --check
	uv build
	uv version
