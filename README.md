# declaw

Secure runtime for AI agents. Spin up isolated sandboxes in milliseconds with built-in guardrails — PII scanning, prompt injection defense, network isolation, and egress filtering.

## Install

```bash
pip install declaw
```

## Quick Start

```python
from declaw import Sandbox

sandbox = Sandbox.create(api_key='your-api-key', template='base', timeout=60)

# Run commands
result = sandbox.commands.run('echo "Hello from a secure sandbox"')
print(result.stdout)

# Read/write files
sandbox.files.write('/tmp/hello.txt', 'Hello World')
content = sandbox.files.read('/tmp/hello.txt')

# Clean up
sandbox.kill()
```

### Async

```python
from declaw import AsyncSandbox

sandbox = await AsyncSandbox.create(api_key='your-api-key', template='python', timeout=60)
result = await sandbox.commands.run('python3 -c "print(1+1)"')
await sandbox.kill()
```

## Why Declaw?

AI agents need to execute code, call APIs, and interact with the world. Declaw gives them a secure sandbox to do it — with built-in guardrails that protect your users and infrastructure.

- **Sub-10ms sandbox creation** — pre-warmed VM pool, no cold starts
- **Network isolation** — per-sandbox firewall with domain and CIDR rules
- **Full file system** — read, write, upload, download files in the sandbox

## Security & Guardrails

Every outbound request from the sandbox passes through a configurable security pipeline.

### PII Scanning

Detect and redact sensitive data before it leaves the sandbox.

```python
from declaw import Sandbox, SecurityPolicy, PIIConfig

sandbox = Sandbox.create(
    security=SecurityPolicy(
        pii=PIIConfig(
            enabled=True,
            types=['ssn', 'credit_card', 'email', 'phone', 'api_key'],
            action='redact',
        ),
    ),
)
```

### Prompt Injection Defense

Block prompt injection attempts in agent outputs.

```python
from declaw import SecurityPolicy, InjectionDefenseConfig

sandbox = Sandbox.create(
    security=SecurityPolicy(
        injection_defense=InjectionDefenseConfig(
            enabled=True,
            action='block',
            threshold=0.85,
        ),
    ),
)
```

### Toxicity, Code Security & Invisible Text

```python
sandbox = Sandbox.create(
    security=SecurityPolicy(
        toxicity=ToxicityConfig(enabled=True, action='block', threshold=0.7),
        code_security=CodeSecurityConfig(enabled=True, action='log'),
        invisible_text=InvisibleTextConfig(enabled=True, action='block'),
    ),
)
```

### Network Policies

```python
from declaw import Sandbox, NetworkPolicy

# Allow only specific domains
sandbox = Sandbox.create(
    network=NetworkPolicy(allow_out=['api.openai.com', 'huggingface.co']),
)

# Block all egress
isolated = Sandbox.create(
    network=NetworkPolicy(deny_out=['ALL_TRAFFIC']),
)
```

### Data Transformation

Transform sensitive values in-flight.

```python
from declaw import SecurityPolicy, TransformationRule

sandbox = Sandbox.create(
    security=SecurityPolicy(
        transformations=[
            TransformationRule(
                pattern=r'sk-[a-zA-Z0-9]+',
                replacement='[API_KEY]',
                direction='egress',
            ),
        ],
    ),
)
```

### Combining Guardrails

All guardrails compose — enable multiple and they run in sequence:

```python
sandbox = Sandbox.create(
    api_key='your-api-key',
    template='ai-agent',
    timeout=300,
    network=NetworkPolicy(allow_out=['api.openai.com', 'api.anthropic.com']),
    security=SecurityPolicy(
        pii=PIIConfig(enabled=True, action='redact', types=['ssn', 'credit_card']),
        injection_defense=InjectionDefenseConfig(enabled=True, action='block'),
        toxicity=ToxicityConfig(enabled=True, action='log'),
        invisible_text=InvisibleTextConfig(enabled=True, action='block'),
    ),
)
```

## Templates

| Template | Description |
|----------|-------------|
| `base` | Minimal Linux |
| `python` | Python 3.12 with pip |
| `node` | Node.js 22 LTS with npm |
| `code-interpreter` | Python with data science libraries |
| `ai-agent` | Python + Node.js + AI/ML tools |
| `mcp-server` | MCP server runtime |
| `web-dev` | Node.js + browser testing |
| `devops` | Docker, Terraform, kubectl |

## API

```python
# Create sandbox
sandbox = Sandbox.create(template, api_key, timeout, network, security)

# Commands
result = sandbox.commands.run('ls -la')
for chunk in sandbox.commands.stream('python script.py'):
    print(chunk)

# Files — `path` is the literal absolute path inside the sandbox.
# Files appear at exactly that path — no remapping, no bridge directory.
sandbox.files.write(path, content)
data = sandbox.files.read(path)
entries = sandbox.files.list('/')

# PTY (interactive terminal)
pty = sandbox.pty.create(cols=80, rows=24)

# Lifecycle
sandbox.kill()
```

## License

Apache-2.0
