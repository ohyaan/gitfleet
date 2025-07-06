# GitFleet

GitFleet is a tool for managing multiple Git repositories and GitHub release assets through a single configuration file. It simplifies repository and asset synchronization across teams and environments.

## Key Features

- **Batch Management**: Clone and update multiple repositories simultaneously
- **GitHub Release Asset Management**: Download and extract assets from GitHub releases
- **Flexible Configuration**: Support for YAML (recommended) and JSON formats
- **Flexible Revision Control**: Support for SHA1 hashes, tags, and branches
- **Git Submodule Integration**: Support for Git submodule
- **Shallow Clone Support**: Save bandwidth and storage for large repositories
- **Anchor Functionality**: Lock repository revisions for reproducible environments

## Requirements

- Python 3.12 or later (zero external dependencies for JSON configuration)
- Git command-line tool
- PyYAML library (only required when using YAML configuration files)

## Installation

```bash
curl -L -o gitfleet https://github.com/ohyaan/gitfleet/blob/main/gitfleet.py
chmod +x gitfleet
mv gitfleet /usr/local/bin
```

### Installing PyYAML (Optional)

If you want to use YAML configuration files (recommended), install PyYAML:

```bash
# Using pip
pip install PyYAML

# Using uv
uv add PyYAML
```

**Note:** GitFleet will work without PyYAML if you only use JSON configuration files. YAML support is optional and PyYAML is only imported when a YAML file is actually loaded.

## Quick Start Guide

1. Create a `gitfleet.yaml` file in your project's root directory
2. Define your repositories and/or releases in the configuration
3. Run `gitfleet` to synchronize all repositories and download assets

GitFleet automatically searches for configuration files in this order:
1. `gitfleet.yaml`
2. `gitfleet.yml` 
3. `gitfleet.json`

### Example `gitfleet.yaml`

```yaml
schemaVersion: v1
repositories:
  - src: https://github.com/xxx/repo1.git
    dest: external/repo1
    revision: refs/tags/v1
  - src: git@github.com:yyy/repo2.git
    dest: external/repo2
    revision: refs/heads/main
releases:
  - url: https://github.com/example/repo
    tag: v1.2.3
    assets:
      - name: "tool-linux-x86_64.tar.gz"
        dest: external/tools
        extract: true
      - name: "data-archive.zip"
        dest: external/data
        extract: true
      - name: "README.txt"
        dest: external/docs
        extract: false
```

### Example `gitfleet.json`

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
  ],
  "releases": [
    {
      "url": "https://github.com/example/repo",
      "tag": "v1.2.3",
      "assets": [
        { "name": "tool-linux-x86_64.tar.gz", "dest": "external/tools", "extract": true },
        { "name": "data-archive.zip", "dest": "external/data", "extract": true },
        { "name": "README.txt", "dest": "external/docs", "extract": false }
      ]
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
├── external/        # Directory for managed repositories and assets
│   ├── repo1/       # First managed repository
│   ├── repo2/       # Second managed repository
│   └── assets/      # Downloaded release assets
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

#### Revision Formats

GitFleet supports three revision formats:
- **SHA1**: `"revision": "a1b2c3d4e5f6"` (exact commit)
- **Tags**: `"revision": "refs/tags/v1"` (specific version)
- **Branches**: `"revision": "refs/heads/main"` (latest on branch)

### Release Configuration Options

Add a top-level `releases` property to your configuration file. Each release entry supports the following properties:

| Property      | Description                                              | Required | Default |
|---------------|----------------------------------------------------------|----------|---------|
| `url`         | GitHub repository URL (HTTPS)                            | Yes      | -       |
| `tag`         | Release tag (e.g., `v1.2.3`)                            | Yes      | -       |
| `assets`      | List of asset file objects to download                   | Yes      | -       |

Each file object in `assets` supports:

| Property   | Description                                 | Required | Default |
|------------|---------------------------------------------|----------|---------|
| `name`     | Asset file name in the release              | Yes      | -       |
| `dest`     | Local destination path (relative/absolute)  | Yes      | -       |
| `extract`  | Extract archive after download              | No       | `true`  |

#### Example: Downloading and Extracting Release Assets

```yaml
schemaVersion: v1
releases:
  - url: https://github.com/example/repo
    tag: v1.2.3
    assets:
      - name: "tool-linux-x86_64.tar.gz"
        dest: external/tools
        extract: true
      - name: "data-archive.zip"
        dest: external/data
        extract: true
      - name: "README.txt"
        dest: external/docs
        extract: false
```

- 各ファイルごとに保存先や展開有無を柔軟に指定できます。
- `extract` を省略した場合は `true` となります。

### Notes
- Release assets are always fetched by tag.
- Extraction is supported for the listed archive formats only.
- The `releases` section is optional and backward compatible.
- All features work with both YAML and JSON configuration files.

## Advanced Usage

### Anchoring Repositories

Lock all your repositories to specific commit SHAs for reproducibility:

```bash
gitfleet --anchor           # Update config file in place
gitfleet --anchor fleet-anchored.json  # Save to a new file
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

### Working with SubFleet

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
gitfleet
# Process default configuration file (searches for gitfleet.yaml, gitfleet.yml, then gitfleet.json)

gitfleet --dry-run
# Dry run to see what would happen

gitfleet --force-shallow-clone
# Force shallow clones for all repositories

gitfleet --anchor anchored-fleet.yaml
# Anchor all repositories and save to new file

gitfleet --parallel 8
# Use more workers for faster processing

gitfleet --verbose
# Enable verbose logging
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

releases:
  - url: https://github.com/example/repo
    tag: v1.2.3
    assets:
      - name: "tool-linux-x86_64.tar.gz"
        dest: external/tools
        extract: true
      - name: "data-archive.zip"
        dest: external/data
        extract: true
      - name: "README.txt"
        dest: external/docs
        extract: false
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
5. **Organize repositories and assets** in logical directory structures under `external/`

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.