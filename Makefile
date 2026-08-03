all: tests lint build-check

.PHONY: tests
tests:
	cd src && python3 -m unittest discover -v -s ../tests

pip-update:
	@./scripts/ensure-venv.sh
	# Update Python
	python3 -m venv --upgrade .venv
	# Update pip
	python -m pip install -U pip
	# Install or update all development time pip dependencies
	# local linting matches continuous integration
	python -m pip install -U -e ".[dev]"

lint:
	@./scripts/ensure-venv.sh
	# Requires ruff and basedpyright: make pip-update
	ruff check
	basedpyright
	ruff format --check --diff

lint-github:
	@# NOTE: ./scripts/ensure-venv.sh doesn't work in Github workflows
	@# NOTE: We don't use pyproject.toml dependencies (pip install ".[dev]")
	@#       because we do not want to install ocsf-schema-compiler.
	# Requires ruff and basedpyright: python -m pip install -U basedpyright ruff
	ruff check --output-format=github
	basedpyright
	ruff format --check --diff

build-check:
	@# NOTE: ./scripts/ensure-venv.sh doesn't work in Github workflows
	@# NOTE: Locally this should be done in a fresh virtual environment
	@# NOTE: We don't use pyproject.toml dependencies (pip install ".[dev]")
	@#       because we do not want to install ocsf-schema-compiler.
	@#       We want to test that the flit install works.
	# Requires Flit: python -m pip install -U flit
	# Build, install locally, and attempt to run
	flit build
	flit install
	ocsf-schema-compiler -h

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
