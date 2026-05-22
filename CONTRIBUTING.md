# Contributing to ShellLite

First off, thank you for considering contributing to ShellLite! It's people like you that make ShellLite such a great tool.

## Getting Started

1. **Fork the repository** on GitHub.
2. **Clone your fork** locally:

   ```bash
   git clone https://github.com/your-username/shell-lite.git
   cd shell-lite
   ```

3. **Set up your environment**:
   We recommend using a virtual environment:
   ```bash
   python -m venv venv
   # Windows
   .\venv\Scripts\activate
   # Linux/macOS
   source venv/bin/activate
   ```

4. **Install dependencies**:
   ```bash
   pip install -e .
   pip install prompt_toolkit build twine llvmlite pytest
   ```

## Development Workflow

1. Create a branch for your feature or fix:
   ```bash
   git checkout -b feature/amazing-feature
   ```

2. Make your changes.
3. Run the tests to ensure nothing is broken (see below).
4. Commit your changes. Please write clear, and descriptive commit messages.

## Running Tests

ShellLite has a suite of tests located in the `tests` directory.

To run the test suite with pytest:
```bash
pytest tests/
```

Please verify that your updates do not break anything :)

## Pull Request Process

1. Push your branch to GitHub.
2. Open a Pull Request against the `main` branch of `ShellLite/ShellLite`.
3. Describe your changes detailedly.
4. Wait for review!

## Code Style

- **Python**: Please follow PEP 8 standards.
- **ShellLite**: Ensure scripts are readable and follow the "English like" philosophy.

## Reporting Bugs

If you find a bug, please create an Issue on GitHub or contact Shrey at contact@shelllite.tech. Include:
- Operating System details.
- ShellLite version.
- A minimal code snippet that reproduces the error.
