# Contributing to Facto

Thank you for your interest in contributing to Facto! We welcome contributions from the community.

## Getting Started

### Prerequisites

- Docker and Docker Compose
- Go 1.21+
- Rust 1.70+
- Python 3.10+
- Node.js 18+

### Development Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/facto-ai/facto.git
   cd facto
   ```

2. Start infrastructure:
   ```bash
   docker compose up -d
   ```

3. Build services:
   ```bash
   # Ingestion service (Rust)
   cd server/ingestion && cargo build --release

   # Processor (Go)
   cd server/processor && go build -o processor .

   # API (Go)
   cd server/api && go build -o api .
   ```

4. Install Python SDK for testing:
   ```bash
   pip install -e sdk/python
   ```

## Making Contributions

### First-Time Setup: Install Git Hooks

**Required step!** This ensures all tests pass before any push:

```bash
bash scripts/install_hooks.sh
```

This installs a pre-push hook that automatically runs unit and security tests before allowing pushes.

### Running Tests

Facto has a comprehensive test suite. Use the master test runner:

```bash
# Fast mode (unit + security) — runs automatically on push
python run_tests.py --fast

# Full suite (requires running services)
python run_tests.py

# Include load tests
python run_tests.py --with-load
```

**Test categories:**
| Category | Command | Requires Services |
|----------|---------|-------------------|
| Unit | `pytest sdk/python/tests` | No |
| Security | `python tests/security/test_tamper_resistance.py` | No |
| Integration | `pytest tests/integration` | Yes |
| Load | `python tests/load/load_test.py` | Yes |

### Pull Request Process

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. **Install hooks**: `bash scripts/install_hooks.sh`
4. Make your changes
5. **Run tests**: `python run_tests.py`
6. Commit your changes (`git commit -m 'Add amazing feature'`)
7. Push to your branch — tests run automatically
8. Open a Pull Request

### Code Style

- **Go**: Follow standard Go formatting (`gofmt`)
- **Rust**: Follow standard Rust formatting (`cargo fmt`)
- **Python**: Follow PEP 8
- **TypeScript**: Use Prettier

## Questions?

Open an issue or start a discussion. We're happy to help!
