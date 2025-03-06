# GitFleet

GitFleet is a tool for managing multiple Git repositories through a single configuration file.
It simplifies repository synchronization across teams and environments.

Supports both YAML and JSON configuration formats with automatic detection.

## Key Features

- **Batch Management**: Clone and update multiple repositories simultaneously
- **Flexible Configuration**: Support for YAML (recommended) and JSON formats
- **Flexible Revision Control**: Support for SHA1 hashes, tags, and branches
- **Git Submodule Integration**: Support for Git submodule
- **Shallow Clone Support**: Save bandwidth and storage for large repositories
- **Anchor Functionality**: Lock repository revisions for reproducible environments

## Requirements

- Python 3.7 or later (zero external dependencies)
- Git command-line tool

## Installation

```bash
curl -L -o gitfleet https://github.com/ohyaan/gitfleet/blob/main/gitfleet.py
chmod +x gitfleet
mv gitfleet /usr/local/bin
```

## Quick Start Guide

1. Create a `gitfleet.yaml` file in your project's root directory
2. Define your repositories in the configuration
3. Run `gitfleet` to synchronize all repositories

GitFleet automatically searches for configuration files in this order:
1. `gitfleet.yaml`
2. `gitfleet.yml` 
3. `gitfleet.json`

Example `gitfleet.yaml`:
```yaml
schemaVersion: v1
repositories:
  - src: https://github.com/xxx/repo1.git
    dest: external/repo1
    revision: refs/tags/v1
  - src: git@github.com:yyy/repo2.git
    dest: external/repo2
    revision: refs/heads/main
```

JSON format is also supported (`gitfleet.json`):
```json
{
  "schemaVersion": "v1",
  "repositories": [
    {
      "src": "https://github.com/xxx/repo1.git",
      "dest": "external/repo1",
      "revision": "refs/tags/v1"
    },
    {
      "src": "git@github.com:yyy/repo2.git",
      "dest": "external/repo2",
      "revision": "refs/heads/main"
    }
  ]
}
```

## Configuration Reference

### Project Structure Example
```
my-project/
├── gitfleet.yaml    # Primary config file (YAML format - recommended)
├── src/             # Your project source code
├── external/        # Directory for managed repositories
│   ├── repo1/       # First managed repository
│   └── repo2/       # Second managed repository
└── ...
```

**Configuration File Priority:**
GitFleet automatically detects and uses the first available configuration file:
1. `gitfleet.yaml`
2. `gitfleet.yml` 
3. `gitfleet.json`

### Repository Configuration Options

Each repository entry supports the following properties:

| Property | Description | Required | Default |
|----------|-------------|----------|---------|
| `src` | Repository URL (HTTPS or SSH) | Yes | - |
| `dest` | Local destination path | Yes | - |
| `revision` | Git revision specification | Yes | - |
| `shallow-clone` | Enable shallow clone | No | `false` |
| `clone-submodule` | Clone submodule | No | `false` |
| `clone-subfleet` | Process nested fleet file | No | `false` |

### Revision Formats

GitFleet supports three revision formats:
- **SHA1**: `"revision": "a1b2c3d4e5f6"` (exact commit)
- **Tags**: `"revision": "refs/tags/v1"` (specific version)
- **Branches**: `"revision": "refs/heads/main"` (latest on branch)

## Advanced Usage

### Anchoring Repositories

Lock all your repositories to specific commit SHAs for reproducibility:

```bash
# Update config file in place
gitfleet --anchor

# Save to a new file
gitfleet --anchor fleet-anchored.json
```

#### Use Cases for Anchoring:
- **Reproducible Builds**: Ensure consistent environments
- **Release Management**: Snapshot dependencies for releases
- **Debugging**: Record exact repository states for troubleshooting

### Working with Submodule

Enable submodule processing with the `clone-submodule` option:

```yaml
schemaVersion: v1
repositories:
  - src: https://github.com/xxx/repo1.git
    dest: external/repo1
    revision: refs/tags/v1
    clone-submodule: true
```

###  Working with SubFleet

Support hierarchical repository management with `clone-subfleet`:

```yaml
schemaVersion: v1
repositories:
  - src: https://github.com/username/sub-project.git
    dest: external/sub-project
    revision: refs/heads/main
    clone-subfleet: true
```

GitFleet will process the `gitfleet.yaml` (or `gitfleet.json`) found in the sub repository.

## Command Line Options

```bash
gitfleet [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `-h, --help` | Show help message and exit |
| `--version` | Show program version |
| `--dry-run` | Show what would be done without executing |
| `--force-shallow-clone` | Force shallow clone for all repositories |
| `--anchor [FILE]` | Anchor repositories to current SHA1 commits |
| `--parallel N` | Maximum number of concurrent workers (default: 4) |
| `--verbose` | Enable verbose output with detailed logging |

### Examples

```bash
# Process default configuration file (searches for gitfleet.yaml, gitfleet.yml, then gitfleet.json)
gitfleet

# Dry run to see what would happen
gitfleet --dry-run

# Force shallow clones for all repositories
gitfleet --force-shallow-clone

# Anchor all repositories and save to new file
gitfleet --anchor anchored-fleet.yaml

# Use more workers for faster processing
gitfleet --parallel 8

# Enable verbose logging
gitfleet --verbose
```

## Complete Configuration Example

Here's a comprehensive example showcasing all available features:

```yaml
schemaVersion: v1
repositories:
  # Basic repository
  - src: https://github.com/example/basic-repo.git
    dest: external/basic-repo
    revision: refs/heads/main

  # Repository with specific tag
  - src: https://github.com/example/versioned-repo.git
    dest: external/versioned-repo
    revision: refs/tags/v2.1.0

  # Repository with specific commit SHA
  - src: https://github.com/example/locked-repo.git
    dest: external/locked-repo
    revision: a1b2c3d4e5f67890abcdef1234567890abcdef12

  # Repository with submodules
  - src: git@github.com:private/repo-with-submodules.git
    dest: external/repo-with-submodules
    revision: refs/heads/develop
    clone-submodule: true

  # Repository with nested fleet
  - src: https://github.com/example/meta-project.git
    dest: external/meta-project
    revision: refs/heads/main
    clone-subfleet: true

  # Large repository with shallow clone
  - src: https://github.com/example/large-repo.git
    dest: external/large-repo
    revision: refs/heads/main
    shallow-clone: true
```

## Troubleshooting

### Common Issues

**Q: GitFleet can't find my configuration file**
```
Error: Cannot find fleet configuration file in /path/to/directory. Looking for: gitfleet.yaml, gitfleet.yml, gitfleet.json
```
A: Ensure at least one of the supported configuration files exists in your current directory. GitFleet searches for files in this priority order: `gitfleet.yaml` → `gitfleet.yml` → `gitfleet.json`

**Q: Repository clone fails with permission errors**
```
Error: Failed to clone repository
```
A: Check your SSH keys or access credentials. For private repositories, ensure proper authentication:
```bash
# Test SSH access
ssh -T git@github.com

# Or use HTTPS with credentials
git config --global credential.helper store
```

**Q: Submodule processing fails**
A: Ensure the repository has proper `.gitmodules` file and submodule URLs are accessible.

**Q: Performance is slow with many repositories**
A: Increase the number of workers:
```bash
gitfleet --parallel 8
```

### Best Practices

1. **Use shallow clones for large repositories** to save bandwidth and storage
2. **Pin specific versions** using tags or SHA1 for production environments
3. **Test with --dry-run** before applying changes to important projects
4. **Use anchoring** to create reproducible snapshots of your dependencies
5. **Organize repositories** in logical directory structures under `external/`

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.