# Publishing ocsf-schema-compiler
This project publishes the **ocsf-schema-compiler** package to PyPI. We can also manually publish to TestPyPI.

This project uses [Flit](https://flit.pypa.io/) to build package distributions, but not for publishing. Publishing is done via GitHub releases, utilizing the [pypa/gh-action-pypi-publish](https://github.com/pypa/gh-action-pypi-publish) action.

Much of the publishing is based on the tutorial [How to Publish an Open-Source Python Package to PyPI — Real Python](https://realpython.com/pypi-publish-python-package/), though using Flit as suggested later in the article.

The publishing flow requires the project's version to be bumped up, along with creating a Git tag with the same version prefixed by "v". Publishing employs GitHub's Releases mechanism, which triggers the publish GitHub actions defined in this project. The action ensures that the version has been changed and the related Git tag exists, and then publishes the package to PyPI.

We can also manually trigger a test publish that works the same way, except that it publishes to TestPyPI.

## Publishing step 1: update project version
The version is defined in the `__version__` variable in [`src/ocsf_schema_compiler/__init__.py`](https://github.com/ocsf/ocsf-schema-compiler/blob/main/src/ocsf_schema_compiler/__init__.py).

Updating the version requires a normal pull request.

## Publishing step 2 (optional): create git tag and test publish
A Git tag must be created with the same version with a "v" prefix. This can be created during a release or beforehand via `git` on the command line.

Creating a tag before release allows us to manually publish to TestPyPI at [ocsf-schema-compiler · TestPyPI](https://test.pypi.org/project/ocsf-schema-compiler/) using this repo's "Test publish package to TestPyPI" GitHub action defined in [`.github/workflows/test-publish.yaml`](https://github.com/ocsf/ocsf-schema-compiler/blob/main/.github/workflows/test-publish.yaml). The test-publish action requires the `testpypi` GitHub environment.

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

## Publishing step 3: release
Create a new release with a tag or select a draft release on the [Releases](https://github.com/ocsf/ocsf-schema-compiler/releases) page, then click "Publish release". This will trigger the GitHub action in [`.github/workflows/publish.yaml`](https://github.com/ocsf/ocsf-schema-compiler/blob/main/.github/workflows/publish.yaml) that publishes the package to PyPI. The publish action requires the `pypi` GitHub environment.

## Optional: manually checking everything
These steps are optional. The continuous integration and publish actions have this covered. However, for the paranoid, we can manually double-check everything locally.

```shell
# If in a virtual environment
deactivate
# Clean up everything, including .venv
make clean-up

# Create fresh virtual environment
python3 -m venv .venv
source ./.venv/bin/activate

# Code does not have any dependencies
# Running tests before installing anything ensure this remains true
make tests

python -m pip install ".[dev]" flit
make lint
make build-check
```

The pre-publishing checks require the project's version to be updated, and the related Git tag exists. The check is run with the `pre-publish-check` target in the [`Makefile`](https://github.com/ocsf/ocsf-schema-compiler/blob/main/Makefile). This target runs the [`scripts/pre-publish-check.sh`](https://github.com/ocsf/ocsf-schema-compiler/blob/main/scripts/pre-publish-check.sh) script, which requires a virtual environment.

This check installs the latest release of **ocsf-schema-compiler** from PyPI, so you will likely want to remove the virtual environment afterwards. The `pre-test-publish-check` target work the same, though installs from TestPyPI.

```shell
# Create virtual environment if it doesn't already exist
python3 -m venv .venv
source ./.venv/bin/activate

# Run the check
make pre-publish-check
# Alternately run `pre-test-publish-check` to verify against TestPyPI
make pre-test-publish-check

# This virtual environment now oddly includes ocsf-schema-compiler itself
# Best to clean up and start over
deactivate
make clean-all
```

If everything works, the actual publishing proceed without issues.
