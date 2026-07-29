# OCSF Schema Compiler
This is a Python library and command-line tool for compiling the Open Cybersecurity Schema Framework (OCSF) schema, specifically the schema at https://github.com/ocsf/ocsf-schema.

This project is published to PyPI: [ocsf-schema-compiler · PyPI](https://pypi.org/project/ocsf-schema-compiler/).

## Getting started
There are three ways to use the OCSF Schema Compiler:
1. As a command-line tool, installed from PyPI.
2. As a library, installed from PyPI.
3. As a developer working on this project.

Python version 3.14 or later is required. The core project code does not require any dependencies, though optional developer dependencies are used (see below).

## Using ocsf-schema-compiler as a command-line tool
Create a virtual environment then install with `pip`. For example:
```shell
python3 -m venv .venv
source ./.venv/bin/activate
python -m pip install ocsf-schema-compiler
```

Running from this environment is now a matter of calling `ocsf-schema-compiler`:
```shell
ocsf-schema-compiler -h
```

The basic usage is passing the base directory of a schema to the compiler and capturing the output to a file.
```shell
ocsf-schema-compiler path/to/ocsf-schema > schema.json
```

## Using ocsf-schema-compiler as a library
Create a virtual environment then install with `pip`. For example:
```shell
python3 -m venv .venv
source ./.venv/bin/activate
python -m pip install ocsf-schema-compiler
```

The compiler is implemented in the `SchemaCompiler` class. The class constructor accepts the same options as the command-line tool. The class's `compile` method does the heavy lifting, returning a `dict` containing the compiled schema. Specifically, `compiler` returns an `ocsf_schema_compiler.jsonish.JObject`, which is a type alias for JSON-compatible `dict`.
```python
from pathlib import Path
from ocsf_schema_compiler.compiler import SchemaCompiler


compiler = SchemaCompiler(Path("path/to/ocsf-schema"))
output = compiler.compile()
```

The returned `compile_version` 1 structure is documented in [Compiled schema format](https://github.com/ocsf/ocsf-schema-compiler/blob/main/docs/format.md).

See [`ocsf_schema_compiler.__main__`](https://github.com/ocsf/ocsf-schema-compiler/blob/main/src/ocsf_schema_compiler/__main__.py) for a working example.

## Developing ocsf-schema-compiler
The recommended way to work on OCSF projects is to create fork in your own GitHub profile or organization. Create your fork of [this repo](https://github.com/ocsf/ocsf-schema-compiler) using the [GitHub CLI](https://cli.github.com/) tool (or, more painfully, manually).

This project requires **Python 3.14 or later**; otherwise, it has no runtime dependencies. This means you can run it directly from a cloned repo's `src` directory without creating a virtual environment.

```shell
cd path/to/ocsf-schema-compiler
cd src
python3 -m ocsf_schema_compiler ~/path/to/ocsf-schema > ~/path/to/output/schema.json
```

This project includes regression tests in the `tests` directory, built using the `unittest` library. These can also be run without a virtual environment so long as `python3` refers to **Python 3.14 or later**. The tests can be run with the [`Makefile`](https://github.com/ocsf/ocsf-schema-compiler/blob/main/Makefile) target `tests`.
```shell
make tests
```

This project uses [basedpyright](https://docs.basedpyright.com/latest/) for type checking and [Ruff](https://docs.astral.sh/ruff/) for linting and code formatting.

Basedpyright was picked as an alternative to Pylance because I'm using the open-source and telemetry-free [VSCodium](https://vscodium.com/) variation of VS Code. The Microsoft-proprietary Pylance extension (part of the Python extension) does not work in VSCodium by design. Basedpyright also offers other benefits: it is strict by default and includes additional type checking rules. Extensions are available for both VSCodium and VS Code; in both cases look for **"BasedPyright"** by detachhead. Use in VS Code does, however, take a little more work. I hope Pyright fans — and especially VS Code users — will find this workable, and perhaps consider using the privacy-focused VSCodium themselves.

The choice of Ruff should be less controversial: it is the current favorite for Python linting and code formatting. The formatting is very similar to [Black](https://black.readthedocs.io/en/stable/) with some minor differences (which I consider improvements).

Use of these tools requires a virtual environment. With the virtual environment activated, the linting and formatting can be run with the [`Makefile`](https://github.com/ocsf/ocsf-schema-compiler/blob/main/Makefile) target `lint`.

Integrating basedpyright and Ruff with your editor is recommended. In both cases, these tools will pick up the configuration in this project's [`pyproject.toml`](https://github.com/ocsf/ocsf-schema-compiler/blob/main/pyproject.toml) file.
* [Editor integration | Ruff](https://docs.astral.sh/ruff/editors/)
* [IDEs - basedpyright](https://docs.basedpyright.com/latest/installation/ides/)

Note: this project's `.gitignore` assumes the virtual environment is at `.venv`.

```shell
# A standard Python virtual environment works fine
python3 -m venv .venv
source ./.venv/bin/activate

# Install the tools
python -m pip install ".[dev]"

# Now the lint target will work
make lint
```

The `dev` extra pins basedpyright and Ruff to a minor version so that local linting matches continuous integration. Both tools add and promote rules in minor releases, which can otherwise fail the lint job on unchanged code. Raise the bounds in [`pyproject.toml`](https://github.com/ocsf/ocsf-schema-compiler/blob/main/pyproject.toml) deliberately, along with any resulting lint fixes.

Also, with a virtual environment, a local install can be used to run the compiler.
```shell
# A standard Python virtual environment works fine
python3 -m venv .venv
source ./.venv/bin/activate

python -m pip install -e .
```

To ensure the project can be built for distribution, the `build-check` target in the [`Makefile`](https://github.com/ocsf/ocsf-schema-compiler/blob/main/Makefile) can be used. This project is built with [Flit](https://flit.pypa.io/), a modern minimal build and publishing tool. It can be run locally to ensure the project remains buildable. This target runs `flit build` and `flit install` to build the package and install it locally, and then runs `ocsf-schema-compiler -h` to verify it works.
```shell
# Create virtual environment if it doesn't already exist
python3 -m venv .venv
# Activate it
source ./.venv/bin/activate
# Install Flit
python -m pip install flit

# Run the build check
make build-check
```

## Continuous integration
The continuous integration is done via a GitHub action in [`.github/workflows/ci.yaml`](https://github.com/ocsf/ocsf-schema-compiler/blob/main/.github/workflows/ci.yaml). This action uses the [`Makefile`](https://github.com/ocsf/ocsf-schema-compiler/blob/main/Makefile) targets `test`, `lint-github`, and `build-check`. (The `lint-github` target is a minor variation of the `lint` target with Ruff's GitHub output format option.)

## Publishing
Publishing details are covered in [`docs/publishing.md`](https://github.com/ocsf/ocsf-schema-compiler/blob/main/docs/publishing.md).

## Copyright
Copyright © OCSF a Series of LF Projects, LLC. See [NOTICE](https://github.com/ocsf/ocsf-schema-compiler/blob/main/NOTICE) for details.

## License
This project is distributed under the Apache License Version 2.0. See [LICENSE](https://github.com/ocsf/ocsf-schema-compiler/blob/main/LICENSE) for details.
