# GitFleet

GitFleet is a tool for managing multiple Git repositories through a single configuration file.
It simplifies repository synchronization across teams and environments.

## Key Features

- **Batch Management**: Clone and update multiple repositories simultaneously
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

1. Create a `gitfleet.json` file in your project's root directory
2. Define your repositories in the configuration
3. Run `gitfleet` to synchronize all repositories

Example `gitfleet.json`:
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
├── gitfleet.json    # Configuration file
├── src/             # Your project source code
├── external/        # Directory for managed repositories
│   ├── repo1/       # First managed repository
│   └── repo2/       # Second managed repository
└── ...
```

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

```json
{
  "schemaVersion": "v1",
  "repositories": [
    {
      "src": "https://github.com/xxx/repo1.git",
      "dest": "external/repo1",
      "revision": "refs/tags/v1",
      "clone-submodule": true
    }
  ]
}
```

###  Working with SubFleet

Support hierarchical repository management with `clone-subfleet`:

```json
{
  "schemaVersion": "v1",
  "repositories": [
    {
      "src": "https://github.com/username/sub-project.git",
      "dest": "external/sub-project",
      "revision": "refs/heads/main",
      "clone-subfleet": true
    }
  ]
}
```

GitFleet will process the `gitfleet.json` found in the sub repository.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.