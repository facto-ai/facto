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

### Pull Request Process

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests to ensure nothing is broken
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to your branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

### Code Style

- **Go**: Follow standard Go formatting (`gofmt`)
- **Rust**: Follow standard Rust formatting (`cargo fmt`)
- **Python**: Follow PEP 8
- **TypeScript**: Use Prettier

## Questions?

Open an issue or start a discussion. We're happy to help!
