#!/usr/bin/env python3

import enum
import os
import sys
import shlex
import shutil
import subprocess
import re
import argparse
from argparse import RawTextHelpFormatter
import json
import logging
import concurrent.futures
from typing import Dict, Any, Optional, Tuple
import time
import urllib.request
import urllib.parse
import urllib.error
import zipfile
import tarfile

__version__ = "v1.0.0"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("gitfleet")


class RevisionType(enum.Enum):
    """Git revision type enumeration"""

    SHA1 = enum.auto()
    TAGS = enum.auto()
    HEADS = enum.auto()
    UNKNOWN = enum.auto()


class GitError(Exception):
    """Exception for Git operations"""

    pass


class ConfigError(Exception):
    """Exception for configuration issues"""

    pass


class ReleaseError(Exception):
    """Exception for GitHub release operations"""

    pass


class GitRunner:
    """Handles Git command execution and operations"""

    # Constants
    REVISION_PATTERN = (
        r"(?:(?P<tags>refs/tags/)|(?P<heads>refs/heads/))(?P<refs_target>[\S]+)"
    )
    DEFAULT_CLONE_DEPTH = "1"
    GIT_CONFIG_OPTIONS = "-c advice.detachedHead=false"

    @staticmethod
    def run_command(cmd: str, cwd: Optional[str] = None, dry_run: bool = False) -> str:
        """Execute a Git command

        Args:
            cmd: Command to execute
            cwd: Working directory
            dry_run: If True, only log the command without executing

        Returns:
            Command output as string

        Raises:
            GitError: If command execution fails
        """
        if dry_run:
            logger.info(f"[DRY RUN] Would execute: {cmd}")
            return ""

        logger.debug(f"Executing: {cmd}")
        try:
            start_time = time.time()
            result = (
                subprocess.check_output(shlex.split(cmd), cwd=cwd)
                .decode("utf-8")
                .rstrip()
            )
            duration = time.time() - start_time
            logger.debug(f"Command completed in {duration:.2f}s")
            return result
        except subprocess.CalledProcessError as e:
            raise GitError(f"Git command failed with code {e.returncode}: {cmd}")

    @staticmethod
    def detect_revision_type(revision: str) -> Tuple[RevisionType, Optional[str]]:
        """Detect the type of revision

        Args:
            revision: Git revision string

        Returns:
            Tuple of (RevisionType, reference target if applicable)
        """
        revision_match = re.match(GitRunner.REVISION_PATTERN, revision)

        if not revision_match:
            return RevisionType.SHA1, None

        refs_target = revision_match.groupdict().get("refs_target", "")

        if revision_match.groupdict().get("tags") is not None:
            return RevisionType.TAGS, refs_target
        elif revision_match.groupdict().get("heads") is not None:
            return RevisionType.HEADS, refs_target
        else:
            return RevisionType.UNKNOWN, refs_target

    @staticmethod
    def is_shallow_repository(path: str, dry_run: bool = False) -> bool:
        """Check if the repository is shallow cloned

        Args:
            path: Repository path
            dry_run: If True, assume not shallow in dry run mode

        Returns:
            True if repository is shallow cloned
        """
        if dry_run:
            return False

        try:
            result = GitRunner.run_command(
                "git rev-parse --is-shallow-repository", cwd=path
            )
            return result.lower() == "true"
        except GitError:
            return False

    @staticmethod
    def build_clone_options(
        repository: Dict[str, Any],
        force_shallow_clone: bool,
        revision_type: RevisionType,
        refs_target: Optional[str],
    ) -> str:
        """Build Git clone options

        Args:
            repository: Repository configuration
            force_shallow_clone: Force shallow clone
            revision_type: Type of revision
            refs_target: Reference target (branch or tag name)

        Returns:
            String with Git clone options
        """
        options = [GitRunner.GIT_CONFIG_OPTIONS]

        # Determine if shallow clone should be used
        can_shallow_clone = (
            force_shallow_clone or repository.get("shallow-clone", False)
        ) and revision_type in (RevisionType.HEADS, RevisionType.TAGS)

        if can_shallow_clone and refs_target:
            options.extend(["--depth", GitRunner.DEFAULT_CLONE_DEPTH])
            options.extend(["-b", refs_target, "--single-branch"])

        if repository.get("clone-submodule", False):
            options.append("--recurse-submodule")
            if can_shallow_clone:
                options.append("--shallow-submodule")

        return " ".join(options)


class Repository:
    """Represents a Git repository with operations"""

    def __init__(
        self,
        config: Dict[str, Any],
        working_dir: str,
        force_shallow_clone: bool = False,
        dry_run: bool = False,
    ):
        """Initialize repository

        Args:
            config: Repository configuration
            working_dir: Base directory for relative paths
            force_shallow_clone: Force shallow clone
            dry_run: If True, don't execute commands
        """
        self.config = config
        self.working_dir = working_dir
        self.force_shallow_clone = force_shallow_clone
        self.dry_run = dry_run
        self.setup_paths()
        self.revision_type, self.refs_target = GitRunner.detect_revision_type(
            self.config["revision"]
        )

    def setup_paths(self):
        """Setup repository paths"""
        self.source_url = self.config["src"]
        repo_name = os.path.basename(self.source_url.rstrip("/"))
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]
        self.name = repo_name

        # Resolve destination path
        dest = self.config["dest"].rstrip("/")
        if not os.path.isabs(dest):
            self.dest_path = os.path.abspath(os.path.join(self.working_dir, dest))
        else:
            self.dest_path = dest

    def exists(self) -> bool:
        """Check if repository directory exists

        Returns:
            True if repository exists
        """
        return os.path.exists(self.dest_path) and os.path.isdir(self.dest_path)

    def ensure_parent_directory(self):
        """Ensure parent directory exists"""
        if not self.dry_run:
            try:
                os.makedirs(os.path.dirname(self.dest_path), exist_ok=True)
            except OSError as e:
                raise GitError(f"Failed to create directory for {self.name}: {e}")

    def check_revision_match(self) -> bool:
        """Check if current revision matches the configured one

        Returns:
            True if revisions match
        """
        if self.dry_run:
            return False

        try:
            current_sha1 = GitRunner.run_command(
                "git rev-parse HEAD", cwd=self.dest_path
            )

            if self.revision_type == RevisionType.SHA1:
                return current_sha1.startswith(self.config["revision"])

            elif self.revision_type == RevisionType.TAGS:
                target_sha1 = GitRunner.run_command(
                    f"git rev-list -n 1 {self.config['revision']}", cwd=self.dest_path
                )
                return current_sha1 == target_sha1

            elif self.revision_type == RevisionType.HEADS:
                target_sha1 = GitRunner.run_command(
                    f"git ls-remote origin {self.config['revision']}",
                    cwd=self.dest_path,
                ).split()[0]
                return current_sha1 == target_sha1

            return False
        except GitError:
            return False

    def clone(self):
        """Clone repository"""
        clone_options = GitRunner.build_clone_options(
            self.config, self.force_shallow_clone, self.revision_type, self.refs_target
        )

        cmd = f"git clone {clone_options} {self.source_url} {self.dest_path}"
        logger.info(f"Cloning {self.name} into {self.dest_path}")

        GitRunner.run_command(cmd, dry_run=self.dry_run)

        # Initialize submodule if needed
        if self.config.get("clone-submodule", False):
            logger.info(f"Initializing submodule for {self.name}")
            GitRunner.run_command(
                "git submodule init", cwd=self.dest_path, dry_run=self.dry_run
            )
            GitRunner.run_command(
                "git submodule update", cwd=self.dest_path, dry_run=self.dry_run
            )

    def update(self):
        """Update repository to specified revision"""
        current_dir = os.getcwd()
        try:
            if not self.dry_run:
                os.chdir(self.dest_path)

            # Fetch updates
            GitRunner.run_command("git fetch", cwd=self.dest_path, dry_run=self.dry_run)

            # Check working directory status
            is_dirty = False
            if not self.dry_run:
                is_dirty = bool(
                    GitRunner.run_command("git status -suno", cwd=self.dest_path)
                )
                if is_dirty:
                    logger.warning(f"{self.name}: Working directory is not clean")

            # Update based on revision type
            if self.revision_type == RevisionType.SHA1:
                self._update_sha1(is_dirty)
            elif self.revision_type == RevisionType.TAGS:
                self._update_tag(is_dirty)
            elif self.revision_type == RevisionType.HEADS:
                self._update_branch(is_dirty)
            else:
                raise GitError(f"Invalid revision type for {self.name}")

            # Update submodule if needed
            if self.config.get("clone-submodule", False):
                GitRunner.run_command(
                    "git submodule update --recursive",
                    cwd=self.dest_path,
                    dry_run=self.dry_run,
                )

        finally:
            if not self.dry_run:
                os.chdir(current_dir)

    def _update_sha1(self, is_dirty: bool):
        """Update repository to specific SHA1 commit"""
        needs_update = True

        if not self.dry_run:
            current_sha1 = GitRunner.run_command(
                "git rev-parse HEAD", cwd=self.dest_path
            )
            if current_sha1.startswith(self.config["revision"]):
                logger.info(
                    f"{self.name}: Already at revision {self.config['revision']}"
                )
                needs_update = False

        if needs_update:
            GitRunner.run_command(
                f"git checkout {self.config['revision']}",
                cwd=self.dest_path,
                dry_run=self.dry_run,
            )
            logger.info(f"{self.name}: Checked out revision {self.config['revision']}")

    def _update_tag(self, is_dirty: bool):
        """Update repository to specific tag"""
        needs_update = True

        if not self.dry_run:
            current_sha1 = GitRunner.run_command(
                "git rev-parse HEAD", cwd=self.dest_path
            )
            target_sha1 = GitRunner.run_command(
                f"git rev-list -n 1 {self.config['revision']}", cwd=self.dest_path
            )
            if current_sha1 == target_sha1:
                logger.info(f"{self.name}: Already at tag {self.config['revision']}")
                needs_update = False

        if needs_update:
            target_sha1 = GitRunner.run_command(
                f"git rev-list -n 1 {self.config['revision']}",
                cwd=self.dest_path,
                dry_run=self.dry_run,
            )
            GitRunner.run_command(
                f"git checkout {target_sha1}", cwd=self.dest_path, dry_run=self.dry_run
            )
            logger.info(f"{self.name}: Checked out tag {self.config['revision']}")

    def _update_branch(self, is_dirty: bool):
        """Update repository to latest branch commit"""
        needs_update = True
        branch = self.refs_target

        if not self.dry_run:
            current_sha1 = GitRunner.run_command(
                "git rev-parse HEAD", cwd=self.dest_path
            )
            target_sha1 = GitRunner.run_command(
                f"git ls-remote origin {self.config['revision']}", cwd=self.dest_path
            ).split()[0]
            if current_sha1 == target_sha1:
                logger.info(f"{self.name}: Already at latest commit of {branch}")
                needs_update = False

        if needs_update:
            GitRunner.run_command(
                f"git checkout {branch}", cwd=self.dest_path, dry_run=self.dry_run
            )

            # Pull only if working directory is clean
            if not is_dirty:
                GitRunner.run_command(
                    f"git pull origin {branch}",
                    cwd=self.dest_path,
                    dry_run=self.dry_run,
                )
                logger.info(f"{self.name}: Updated to latest commit of {branch}")
            else:
                logger.warning(
                    f"{self.name}: Skipping git pull - working directory is not clean"
                )

    def process_subfleet(self):
        """Process nested fleet file if specified"""
        if not self.config.get("clone-subfleet", False):
            return

        # Look for fleet config files in the root of the repository
        try:
            subfleet_path = FleetManager.find_fleet_config_file(self.dest_path)
            logger.info(f"Processing nested fleet file: {subfleet_path}")
            fleet_manager = FleetManager(
                self.dest_path,  # Use the repository path as the base directory
                self.force_shallow_clone,
                dry_run=self.dry_run,
            )
            fleet_manager.process()
        except ConfigError as e:
            if self.dry_run:
                logger.info(
                    f"[DRY RUN] Would process nested fleet file in {self.dest_path}"
                )
            else:
                logger.warning(f"Failed to process nested fleet file: {e}")
        except GitError as e:
            logger.warning(f"Failed to process nested fleet file: {e}")

    def get_current_sha1(self) -> str:
        """Get current commit SHA1

        Returns:
            Current commit SHA1
        """
        if self.dry_run:
            return "dry-run-sha1"

        try:
            return GitRunner.run_command("git rev-parse HEAD", cwd=self.dest_path)
        except GitError as e:
            logger.warning(f"Failed to get current SHA1 for {self.name}: {e}")
            return ""

    def sync(self) -> bool:
        """Synchronize repository

        Returns:
            True if successful
        """
        logger.info(f"Processing repository: {self.name} from {self.source_url}")

        try:
            self.ensure_parent_directory()

            should_be_shallow = self.force_shallow_clone or self.config.get(
                "shallow-clone", False
            )
            requires_clean_clone = False

            # Check if repository exists and if state matches requirements
            if self.exists():
                current_is_shallow = GitRunner.is_shallow_repository(
                    self.dest_path, self.dry_run
                )
                revision_matches = self.check_revision_match()

                if should_be_shallow != current_is_shallow or not revision_matches:
                    logger.info(
                        f"{self.name}: Repository state mismatch - performing clean clone"
                    )
                    if not self.dry_run:
                        shutil.rmtree(self.dest_path)
                    requires_clean_clone = True
            else:
                requires_clean_clone = True

            # Clone or update repository
            if requires_clean_clone:
                self.clone()
            else:
                self.update()

            # Process nested fleet if needed
            self.process_subfleet()

            return True
        except GitError as e:
            logger.error(f"Failed to sync repository {self.name}: {e}")
            return False


class ReleaseAsset:
    """Represents a GitHub release asset with download operations"""

    def __init__(
        self,
        config: Dict[str, Any],
        working_dir: str,
        dry_run: bool = False,
    ):
        """Initialize release asset

        Args:
            config: Asset configuration
            working_dir: Base directory for relative paths
            dry_run: If True, don't execute commands
        """
        self.config = config
        self.working_dir = working_dir
        self.dry_run = dry_run
        self.setup_paths()

    def setup_paths(self):
        """Setup asset paths"""
        self.name = self.config["name"]

        # Resolve destination path (dest is required)
        dest = self.config["dest"]
        if not os.path.isabs(dest):
            self.dest_path = os.path.abspath(os.path.join(self.working_dir, dest))
        else:
            self.dest_path = dest

        self.file_path = os.path.join(self.dest_path, self.name)

    def ensure_dest_directory(self):
        """Ensure destination directory exists"""
        if not self.dry_run:
            try:
                os.makedirs(self.dest_path, exist_ok=True)
            except OSError as e:
                raise ReleaseError(f"Failed to create directory {self.dest_path}: {e}")

    def download(self, download_url: str) -> bool:
        """Download asset from URL

        Args:
            download_url: URL to download from

        Returns:
            True if successful
        """
        logger.info(f"Downloading {self.name} to {self.dest_path}")

        if self.dry_run:
            logger.info(f"[DRY RUN] Would download {download_url} to {self.file_path}")
            return True

        try:
            self.ensure_dest_directory()

            # Download with progress
            with urllib.request.urlopen(download_url) as response:
                total_size = int(response.headers.get("Content-Length", 0))

                with open(self.file_path, "wb") as f:
                    downloaded = 0
                    chunk_size = 8192

                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)

                        if total_size > 0:
                            progress = (downloaded / total_size) * 100
                            logger.debug(
                                f"Downloaded {downloaded}/{total_size} bytes ({progress:.1f}%)"
                            )

            logger.info(f"Successfully downloaded {self.name}")
            return True

        except (urllib.error.URLError, IOError) as e:
            logger.error(f"Failed to download {self.name}: {e}")
            return False

    def extract(self) -> bool:
        """Extract archive if specified

        Returns:
            True if successful or no extraction needed
        """
        if not self.config.get("extract", True):
            return True

        if self.dry_run:
            logger.info(f"[DRY RUN] Would extract {self.file_path}")
            return True

        if not os.path.exists(self.file_path):
            logger.error(f"Cannot extract - file not found: {self.file_path}")
            return False

        try:
            if self.name.endswith(".zip"):
                logger.info(f"Extracting ZIP: {self.name}")
                with zipfile.ZipFile(self.file_path, "r") as zip_file:
                    zip_file.extractall(self.dest_path)

            elif self.name.endswith((".tar.gz", ".tgz")):
                logger.info(f"Extracting TAR.GZ: {self.name}")
                with tarfile.open(self.file_path, "r:gz") as tar_file:
                    tar_file.extractall(self.dest_path)

            elif self.name.endswith(".tar"):
                logger.info(f"Extracting TAR: {self.name}")
                with tarfile.open(self.file_path, "r") as tar_file:
                    tar_file.extractall(self.dest_path)

            else:
                logger.info(f"No extraction needed for {self.name}")
                return True

            logger.info(f"Successfully extracted {self.name}")
            return True

        except (zipfile.BadZipFile, tarfile.TarError, IOError) as e:
            logger.error(f"Failed to extract {self.name}: {e}")
            return False


class Release:
    """Represents a GitHub release with asset operations"""

    def __init__(
        self,
        config: Dict[str, Any],
        working_dir: str,
        dry_run: bool = False,
    ):
        """Initialize release

        Args:
            config: Release configuration
            working_dir: Base directory for relative paths
            dry_run: If True, don't execute commands
        """
        self.config = config
        self.working_dir = working_dir
        self.dry_run = dry_run
        self.setup_release_info()
        self.setup_assets()

    def setup_release_info(self):
        """Setup release information"""
        self.url = self.config["url"]
        self.tag = self.config["tag"]

        # Parse GitHub URL to get owner and repo
        if self.url.startswith("https://github.com/"):
            parts = self.url.replace("https://github.com/", "").strip("/").split("/")
            if len(parts) >= 2:
                self.owner = parts[0]
                self.repo = parts[1]
                self.name = f"{self.owner}/{self.repo}"
            else:
                raise ReleaseError(f"Invalid GitHub URL format: {self.url}")
        else:
            raise ReleaseError(f"Only GitHub URLs are supported: {self.url}")

    def setup_assets(self):
        """Setup asset objects"""
        self.assets = []
        for asset_config in self.config.get("assets", []):
            self.assets.append(
                ReleaseAsset(asset_config, self.working_dir, self.dry_run)
            )

    def fetch_release_info(self) -> Dict[str, Any]:
        """Fetch release information from GitHub API

        Returns:
            Release information dictionary

        Raises:
            ReleaseError: If API request fails
        """
        api_url = f"https://api.github.com/repos/{self.owner}/{self.repo}/releases/tags/{self.tag}"

        if self.dry_run:
            logger.info(f"[DRY RUN] Would fetch release info from {api_url}")
            return {"assets": []}

        try:
            logger.debug(f"Fetching release info from {api_url}")
            with urllib.request.urlopen(api_url) as response:
                data = json.loads(response.read().decode("utf-8"))
            return data
        except (urllib.error.URLError, json.JSONDecodeError) as e:
            raise ReleaseError(
                f"Failed to fetch release info for {self.name} tag {self.tag}: {e}"
            )

    def find_asset_download_url(
        self, asset_name: str, release_data: Dict[str, Any]
    ) -> Optional[str]:
        """Find download URL for asset

        Args:
            asset_name: Name of asset to find
            release_data: Release data from GitHub API

        Returns:
            Download URL if found, None otherwise
        """
        for asset in release_data.get("assets", []):
            if asset.get("name") == asset_name:
                return asset.get("browser_download_url")
        return None

    def sync(self) -> bool:
        """Synchronize release assets

        Returns:
            True if successful
        """
        logger.info(f"Processing release: {self.name} tag {self.tag}")

        try:
            # Fetch release information
            release_data = self.fetch_release_info()

            # Process each asset
            success_count = 0
            for asset in self.assets:
                download_url = self.find_asset_download_url(asset.name, release_data)

                if not download_url:
                    logger.error(f"Asset not found in release: {asset.name}")
                    continue

                # Download and extract asset
                if asset.download(download_url) and asset.extract():
                    success_count += 1
                else:
                    logger.error(f"Failed to process asset: {asset.name}")

            total_assets = len(self.assets)
            logger.info(
                f"Processed {success_count}/{total_assets} assets for {self.name}"
            )

            return success_count == total_assets

        except ReleaseError as e:
            logger.error(f"Failed to sync release {self.name}: {e}")
            return False


class ConfigLoader:
    """Handles loading and validating configuration files"""

    @staticmethod
    def load_config(file_path: str) -> Dict[str, Any]:
        """Load configuration from file

        Args:
            file_path: Path to configuration file

        Returns:
            Dictionary with parsed configuration

        Raises:
            ConfigError: If configuration is invalid
        """
        if not os.path.exists(file_path):
            raise ConfigError(f"Configuration file not found: {file_path}")

        file_ext = os.path.splitext(file_path)[1].lower()

        try:
            with open(file_path, "r") as f:
                if file_ext == ".json":
                    config = json.load(f)
                elif file_ext in (".yaml", ".yml"):
                    try:
                        import yaml
                    except ImportError:
                        raise ConfigError(
                            "YAML support requires the 'pyyaml' package. "
                            "Install it with: pip install pyyaml"
                        )
                    config = yaml.safe_load(f)
                else:
                    raise ConfigError(f"Unsupported configuration format: {file_ext}")
        except json.JSONDecodeError as e:
            raise ConfigError(f"Failed to parse JSON configuration file: {e}")
        except ImportError:
            # Re-raise ImportError from yaml import
            raise
        except IOError as e:
            raise ConfigError(f"Failed to read configuration file: {e}")
        except Exception as e:
            # Handle yaml.YAMLError and other YAML-related errors
            if file_ext in (".yaml", ".yml"):
                raise ConfigError(f"Failed to parse YAML configuration file: {e}")
            else:
                raise ConfigError(f"Failed to parse configuration file: {e}")

        # Validate configuration
        ConfigLoader.validate_config(config)

        return config

    @staticmethod
    def validate_config(config: Dict[str, Any]):
        """Validate configuration structure

        Args:
            config: Configuration dictionary

        Raises:
            ConfigError: If configuration is invalid
        """
        if not isinstance(config, dict):
            raise ConfigError("Configuration must be a dictionary")

        # Validate repositories section
        if "repositories" in config:
            if not isinstance(config["repositories"], list):
                raise ConfigError("'repositories' must be a list")

            for idx, repo in enumerate(config["repositories"]):
                if not isinstance(repo, dict):
                    raise ConfigError(f"Repository #{idx} must be a dictionary")

                # Check required fields
                for field in ["src", "dest", "revision"]:
                    if field not in repo:
                        raise ConfigError(
                            f"Repository #{idx} missing required field: {field}"
                        )

                # Validate that clone-subfleet is boolean if present
                if "clone-subfleet" in repo and not isinstance(
                    repo["clone-subfleet"], bool
                ):
                    raise ConfigError(
                        f"Repository #{idx}: 'clone-subfleet' must be a boolean value"
                    )

        # Validate releases section
        if "releases" in config:
            if not isinstance(config["releases"], list):
                raise ConfigError("'releases' must be a list")

            for idx, release in enumerate(config["releases"]):
                if not isinstance(release, dict):
                    raise ConfigError(f"Release #{idx} must be a dictionary")

                # Check required fields
                for field in ["url", "tag", "assets"]:
                    if field not in release:
                        raise ConfigError(
                            f"Release #{idx} missing required field: {field}"
                        )

                # Validate assets
                if not isinstance(release["assets"], list):
                    raise ConfigError(f"Release #{idx}: 'assets' must be a list")

                for asset_idx, asset in enumerate(release["assets"]):
                    if not isinstance(asset, dict):
                        raise ConfigError(
                            f"Release #{idx} asset #{asset_idx} must be a dictionary"
                        )

                    # Check required fields for assets
                    for field in ["name", "dest"]:
                        if field not in asset:
                            raise ConfigError(
                                f"Release #{idx} asset #{asset_idx} missing required field: '{field}'"
                            )

        # Ensure at least one of repositories or releases exists
        if "repositories" not in config and "releases" not in config:
            raise ConfigError(
                "Configuration must contain 'repositories' or 'releases' section"
            )

    @staticmethod
    def save_config(config: Dict[str, Any], file_path: str):
        """Save configuration to file

        Args:
            config: Configuration dictionary
            file_path: Path to save configuration file

        Raises:
            ConfigError: If configuration cannot be saved
        """
        file_ext = os.path.splitext(file_path)[1].lower()

        try:
            with open(file_path, "w") as f:
                if file_ext == ".json":
                    json.dump(config, f, indent=4)
                elif file_ext in (".yaml", ".yml"):
                    try:
                        import yaml
                    except ImportError:
                        raise ConfigError(
                            "YAML support requires the 'pyyaml' package. "
                            "Install it with: pip install pyyaml"
                        )
                    yaml.dump(config, f, default_flow_style=False)
                else:
                    raise ConfigError(f"Unsupported configuration format: {file_ext}")
        except IOError as e:
            raise ConfigError(f"Failed to write configuration file: {e}")


class FleetManager:
    """Manages the entire fleet of repositories"""

    FLEET_CONFIG_NAMES = ["gitfleet.yaml", "gitfleet.yml", "gitfleet.json"]
    SUPPORTED_SCHEMA_VERSIONS = ["v1"]

    def __init__(
        self,
        working_dir: str,
        force_shallow_clone: bool = False,
        dry_run: bool = False,
        max_workers: int = 4,
        base_dir: Optional[str] = None,
        fleet_file_path: Optional[str] = None,
    ):
        """Initialize fleet manager

        Args:
            working_dir: Working directory where gitfleet config is located
            force_shallow_clone: Force shallow clone for all repositories
            dry_run: If True, don't execute commands
            max_workers: Maximum number of concurrent workers
            base_dir: Base directory for relative paths (defaults to working_dir)
            fleet_file_path: Specific fleet file path (if None, auto-detect)
        """
        self.force_shallow_clone = force_shallow_clone
        self.dry_run = dry_run
        self.max_workers = max_workers

        self.working_dir = working_dir

        # Determine fleet file path
        if fleet_file_path:
            self.fleet_path = fleet_file_path
        else:
            self.fleet_path = self.find_fleet_config_file(working_dir)

        # Use provided base_dir or working_dir for relative paths
        self.base_dir = base_dir if base_dir is not None else working_dir

        self.config = None
        self.repositories = []
        self.releases = []

    def check_schema_version(self):
        """Check if the schema version is supported

        Raises:
            ConfigError: If schema version is missing or not supported
        """
        if self.config is None:
            raise ConfigError("Configuration not loaded.")

        schema_version = self.config.get("schemaVersion")
        if not schema_version:
            raise ConfigError("Schema version is required.")
        elif schema_version not in self.SUPPORTED_SCHEMA_VERSIONS:
            raise ConfigError(
                f"Unsupported schema version: {schema_version}. "
                f"Supported versions are: {', '.join(self.SUPPORTED_SCHEMA_VERSIONS)}"
            )
        logger.debug(f"Using schema version: {schema_version}")

    def load(self):
        """Load fleet configuration"""
        logger.info(f"Loading fleet configuration from {self.fleet_path}")
        self.config = ConfigLoader.load_config(self.fleet_path)

        # Check schema version
        self.check_schema_version()

        # Create Repository objects
        self.repositories = []
        for repo_config in self.config.get("repositories", []):
            self.repositories.append(
                Repository(
                    repo_config,
                    self.base_dir,  # Use base_dir for relative paths
                    self.force_shallow_clone,
                    self.dry_run,
                )
            )

        # Create Release objects
        self.releases = []
        for release_config in self.config.get("releases", []):
            self.releases.append(
                Release(
                    release_config,
                    self.base_dir,  # Use base_dir for relative paths
                    self.dry_run,
                )
            )

        logger.info(
            f"Loaded {len(self.repositories)} repositories and {len(self.releases)} releases from configuration"
        )

    def process_sequential(self):
        """Process repositories and releases sequentially"""
        results = []
        for repo in self.repositories:
            results.append(repo.sync())
        for release in self.releases:
            results.append(release.sync())
        return results

    def process_parallel(self):
        """Process repositories and releases in parallel"""
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.max_workers
        ) as executor:
            futures = {}

            # Submit repository tasks
            for repo in self.repositories:
                futures[executor.submit(repo.sync)] = ("repo", repo)

            # Submit release tasks
            for release in self.releases:
                futures[executor.submit(release.sync)] = ("release", release)

            results = []

            for future in concurrent.futures.as_completed(futures):
                item_type, item = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    if item_type == "repo":
                        logger.error(f"Error processing repository {item.name}: {e}")
                    else:
                        logger.error(f"Error processing release {item.name}: {e}")
                    results.append(False)

            return results

    def process(self):
        """Process all repositories

        Returns:
            True if all repositories processed successfully
        """
        if not self.config:
            self.load()

        logger.info(
            f"Processing {len(self.repositories)} repositories and {len(self.releases)} releases"
        )

        total_items = len(self.repositories) + len(self.releases)
        if self.max_workers > 1 and total_items > 1:
            logger.info(f"Using parallel processing with {self.max_workers} workers")
            results = self.process_parallel()
        else:
            logger.info("Using sequential processing")
            results = self.process_sequential()

        success_count = sum(1 for r in results if r)
        logger.info(
            f"Processed {len(results)} items: "
            f"{success_count} succeeded, {len(results) - success_count} failed"
        )

        return all(results)

    def anchor(self, output_path: Optional[str] = None):
        """Anchor repository revisions to current commit SHAs

        Args:
            output_path: Path to save anchored configuration
        """
        if not self.config:
            self.load()

        # Type guard to ensure config is not None
        if self.config is None:
            raise ConfigError("Failed to load configuration.")

        logger.info("Anchoring repository revisions to current commit SHAs")

        # Update repository configurations with current SHAs
        for repo in self.repositories:
            current_sha1 = repo.get_current_sha1()
            if current_sha1:
                # Find and update corresponding repository in configuration
                repositories = self.config.get("repositories", [])
                for repo_config in repositories:
                    if (
                        repo_config["src"] == repo.source_url
                        and repo_config["dest"] == repo.config["dest"]
                    ):
                        repo_config["revision"] = current_sha1
                        logger.info(
                            f"Anchored {repo.name} "
                            f"to {current_sha1[:8]}{'...' if len(current_sha1) > 8 else ''}"
                        )
                        break

        # Save updated configuration
        save_path = output_path or self.fleet_path
        if not self.dry_run:
            ConfigLoader.save_config(self.config, save_path)
            logger.info(f"Saved anchored configuration to {save_path}")
        else:
            logger.info(f"[DRY RUN] Would save anchored configuration to {save_path}")

    @staticmethod
    def find_fleet_config_file(working_dir: str) -> str:
        """Find fleet configuration file in the working directory

        Args:
            working_dir: Directory to search for config files

        Returns:
            Path to the first found configuration file

        Raises:
            ConfigError: If no configuration file is found
        """
        for config_name in FleetManager.FLEET_CONFIG_NAMES:
            config_path = os.path.join(working_dir, config_name)
            if os.path.exists(config_path):
                return config_path

        # If no file found, raise error with all possible names
        config_names_str = ", ".join(FleetManager.FLEET_CONFIG_NAMES)
        raise ConfigError(
            f"Cannot find fleet configuration file in {working_dir}. "
            f"Looking for: {config_names_str}"
        )


def setup_arg_parser():
    """Setup argument parser"""
    parser = argparse.ArgumentParser(
        description="Clone and synchronize repositories as defined in gitfleet configuration",
        formatter_class=RawTextHelpFormatter,
        add_help=False,
    )

    parser.add_argument(
        "-h",
        "--help",
        action="help",
        default=argparse.SUPPRESS,
        help="Show this help message and exit.",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show program's version number and exit.",
    )
    # -f/--fleet option removed as requested

    # Execution control
    parser.add_argument(
        "--force-shallow-clone",
        action="store_true",
        help=(
            "Force shallow clone for all repositories, regardless of their individual configuration."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=("Show what would be done without making any changes."),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help=("Enable verbose output with detailed logging."),
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=4,
        metavar="WORKERS",
        help=(
            "Number of concurrent workers for parallel processing.\n"
            "Set to 1 to disable parallel processing. Default is 4."
        ),
    )

    # Anchoring
    parser.add_argument(
        "--anchor",
        nargs="?",
        metavar="OUTPUT_FILEPATH",
        default=None,
        const="",
        help=(
            "Lock repository revisions to their current commit SHA1s.\n"
            "If OUTPUT_FILEPATH is not specified, updates the input fleet file."
        ),
    )

    return parser


def main():
    """Main entry point"""
    parser = setup_arg_parser()
    args = parser.parse_args()

    # Configure logging
    if args.verbose:
        logger.setLevel(logging.DEBUG)
        logger.debug("Verbose logging enabled")

    if args.dry_run:
        logger.info("Running in dry-run mode - no changes will be made")

    try:
        # Use current directory for fleet file
        current_dir = os.getcwd()

        # Initialize and process fleet
        fleet_manager = FleetManager(
            current_dir,
            args.force_shallow_clone,
            dry_run=args.dry_run,
            max_workers=args.parallel,
        )

        success = fleet_manager.process()

        # Handle anchoring if requested
        if args.anchor is not None:
            output_path = args.anchor or None
            fleet_manager.anchor(output_path)

        if success:
            logger.info("All operations completed successfully!")
            return 0
        else:
            logger.error("Operation failed!")
            return 1

    except ConfigError as e:
        logger.error(f"Configuration error: {e}")
        return 1
    except GitError as e:
        logger.error(f"Git operation error: {e}")
        return 1
    except KeyboardInterrupt:
        logger.info("Operation interrupted by user")
        return 130
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
