all: tests lint build-check

.PHONY: tests
tests:
	cd src && python3 -m unittest discover -v -s ../tests

pip-update:
	@./scripts/ensure-venv.sh
	# Update Python
	python3 -m venv --upgrade .venv
	# Install or update all development time pip dependencies
	# basedpyright and ruff are pinned in pyproject.toml's "dev" extra so that
	# local linting matches continuous integration
	python -m pip install -U ".[dev]" flit

lint:
	@./scripts/ensure-venv.sh
	# Requires ruff and basedpyright: python -m pip install ".[dev]"
	ruff check
	basedpyright
	ruff format --check --diff

lint-github:
	# Requires ruff and basedpyright: python -m pip install ".[dev]"
	ruff check --output-format=github
	basedpyright
	ruff format --check --diff

build-check:
	@# NOTE: ./scripts/ensure-venv.sh doesn't work in Github workflows
	# Requires Flit: python -m pip install flit
	# Build, install locally, and attempt to run
	flit build
	flit install
	ocsf-schema-compiler -h

pre-publish-check:
	./scripts/pre-publish-check.sh

pre-test-publish-check:
	./scripts/pre-publish-check.sh --test

clean:
	rm -rf dist
	rm -rf .ruff_cache
	find src tests \
		-type d -name __pycache__ -delete \
		-or -type f -name '*.py[cod]' -delete \
		-or -type f -name '*$py.class' -delete

clean-all: clean
	rm -rf .venv

cloc:
	cloc --exclude-dir=.venv,.idea .
