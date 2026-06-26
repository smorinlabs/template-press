# **CI/CD with GitHub Actions**

This guide explains how to automate testing, linting, and deployment for the Py Launch Blueprint project using GitHub Actions. [Learn more](../tools/github_actions.md).

## **Workflow Overview**

The CI/CD workflow (`.github/workflows/ci.yaml`) runs on:
- Pushes to `main`
- Pull requests targeting `main`

### **Jobs**
- **Test**: Runs tests on Python 3.12 and 3.13 across Blacksmith ubuntu, macOS, and Windows matrix legs
  - Sets up environment using `uv` and `actions/setup-python`
  - Installs dependencies: `uv sync --all-extras --dev`
  - Runs ty (`uv run ty check`), Ruff (`uvx ruff check`), and pytest (`uvx pytest`)

## **Workflow Configuration**

```yaml
name: CI/CD

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.12", "3.13"]

    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: uv sync --all-extras --dev
      - run: uv run ty check src/template_press/
      - run: uvx ruff check template_press/
      - run: uvx pytest
```

## **Customization**

- **Add more Python versions**:
  ```yaml
  strategy:
    matrix:
      python-version: ["3.12", "3.13"]
  ```
- **Add security scanning**:
  ```yaml
  - name: Run security scan
    run: uvx bandit -r template_press/
  ```
- **Cache dependencies**:
  ```yaml
  - uses: actions/cache@v3
    with:
      path: .venv
      key: venv-${{ runner.os }}-${{ hashFiles('**/pyproject.toml') }}
  ```
