# Publishing ocsf-schema-compiler

This project publishes the **ocsf-schema-compiler** package to PyPI. We can also manually publish to TestPyPI.

This project uses [Flit](https://flit.pypa.io/) to build package distributions, but not for publishing. Publishing is done via GitHub releases, utilizing the [pypa/gh-action-pypi-publish](https://github.com/pypa/gh-action-pypi-publish) action.

Much of the publishing is based on the tutorial [How to Publish an Open-Source Python Package to PyPI — Real Python](https://realpython.com/pypi-publish-python-package/), though using Flit as suggested later in the article.

Publishing employs GitHub's Releases mechanism, which triggers the publish GitHub actions defined in this project. The publish workflow overwrites the package's version based on the release tag. The workflow is here: `.github/workflows/publish.yaml`. The package version defined by `__version__` in `src/ocsf_schema_compiler/__init__.py`.

We can also manually trigger a test publish that works the same way, except that it publishes to TestPyPI.

## Publishing release

Create a new release with a tag or select a draft release on the [Releases](https://github.com/ocsf/ocsf-schema-compiler/releases) page, then click "Publish release". Version tags should be prefixed with "v" and follow [Semantic Versioning](https://semver.org), for example "v1.0.0".

Releasing will trigger the GitHub action at `.github/workflows/publish.yaml`, which publishes the package to PyPI. The publish action requires the `pypi` GitHub environment.

## Test publishing

The Git tag also can be created before the release. This is not needed for normal publishing, but is required for test publishing.

Test publishing is done manually using this repo's "Test publish package to TestPyPI" GitHub action defined in `.github/workflows/test-publish.yaml`. The test-publish action requires the `testpypi` GitHub environment and publishes to TestPyPI at [ocsf-schema-compiler · TestPyPI](https://test.pypi.org/project/ocsf-schema-compiler/).

To create a new tag on the command line, navigate to a local cloned of this repo's `main` branch (not a fork), then use commands similar to the following example for version 1.0.0:

```shell
# Create a nice annotated tag with a message
git tag v1.0.0 -a -m "Release version 1.0.0"
# Or just create the tag
git tag v1.0.0

# Push the tag - this does not require a pull request
git push origin v1.0.0

# Alternately all tags can be pushed
git push origin --tags
```

To trigger the test publish action, run "Test publish package to TestPyPI" for the `main` branch from this repo's [Actions](https://github.com/ocsf/ocsf-schema-compiler/actions) page.

## Optional: manually checking before publishing

These steps are optional. The continuous integration and publish actions have this covered. However, for the paranoid, we can manually double-check everything locally.

```shell
# If in a virtual environment
deactivate
# Clean up everything, including .venv
make clean-all

# Create fresh virtual environment
python3 -m venv .venv
source ./.venv/bin/activate

# Code does not have any dependencies
# Running tests before installing anything ensure this remains true
make tests

python -m pip install -U -e ".[dev]"
make lint

# Checking the build is best done in a clean virtual environment
# It does an install of the ocsf-schema-compiler, and so we don't
# want the editable version installed above to confuse things.
deactivate
make clean-all
python3 -m venv .venv
source ./.venv/bin/activate
# Install the build tool we use: flit
python -m pip install -U flit
# And now we can check the build
make build-check
```
