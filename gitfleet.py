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
import yaml
import logging
import concurrent.futures
from typing import Dict, Any, Optional, Tuple
import time

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
                    f'git rev-list -n 1 {self.config["revision"]}', cwd=self.dest_path
                )
                return current_sha1 == target_sha1

            elif self.revision_type == RevisionType.HEADS:
                target_sha1 = GitRunner.run_command(
                    f'git ls-remote origin {self.config["revision"]}',
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

        # Look for gitfleet.json in the root of the repository
        subfleet_path = os.path.join(self.dest_path, FleetManager.FLEET_CONFIG_NAME)

        if self.dry_run or os.path.exists(subfleet_path):
            logger.info(f"Processing nested fleet file: {subfleet_path}")
            try:
                fleet_manager = FleetManager(
                    self.dest_path,  # Use the repository path as the base directory
                    self.force_shallow_clone,
                    dry_run=self.dry_run,
                )
                fleet_manager.process()
            except (GitError, ConfigError) as e:
                logger.warning(f"Failed to process nested fleet file: {e}")
        else:
            logger.warning(f"Nested fleet file not found: {subfleet_path}")

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
                    config = yaml.safe_load(f)
                else:
                    raise ConfigError(f"Unsupported configuration format: {file_ext}")
        except (json.JSONDecodeError, yaml.YAMLError) as e:
            raise ConfigError(f"Failed to parse configuration file: {e}")
        except IOError as e:
            raise ConfigError(f"Failed to read configuration file: {e}")

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

        if "repositories" not in config:
            raise ConfigError("Configuration must contain 'repositories' key")

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
                    yaml.dump(config, f, default_flow_style=False)
                else:
                    raise ConfigError(f"Unsupported configuration format: {file_ext}")
        except IOError as e:
            raise ConfigError(f"Failed to write configuration file: {e}")


class FleetManager:
    """Manages the entire fleet of repositories"""

    FLEET_CONFIG_NAME = "gitfleet.json"
    SUPPORTED_SCHEMA_VERSIONS = ["v1"]

    def __init__(
        self,
        working_dir: str,
        force_shallow_clone: bool = False,
        dry_run: bool = False,
        max_workers: int = 4,
        base_dir: Optional[str] = None,
    ):
        """Initialize fleet manager

        Args:
            working_dir: Working directory where gitfleet.json is located
            force_shallow_clone: Force shallow clone for all repositories
            dry_run: If True, don't execute commands
            max_workers: Maximum number of concurrent workers
            base_dir: Base directory for relative paths (defaults to working_dir)
        """
        self.force_shallow_clone = force_shallow_clone
        self.dry_run = dry_run
        self.max_workers = max_workers

        self.working_dir = working_dir
        self.fleet_path = os.path.join(working_dir, self.FLEET_CONFIG_NAME)

        # Use provided base_dir or working_dir for relative paths
        self.base_dir = base_dir if base_dir is not None else working_dir

        self.config = None
        self.repositories = []

    def check_schema_version(self):
        """Check if the schema version is supported

        Raises:
            ConfigError: If schema version is missing or not supported
        """
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

        logger.info(f"Loaded {len(self.repositories)} repositories from configuration")

    def process_sequential(self):
        """Process repositories sequentially"""
        results = []
        for repo in self.repositories:
            results.append(repo.sync())
        return results

    def process_parallel(self):
        """Process repositories in parallel"""
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.max_workers
        ) as executor:
            futures = {executor.submit(repo.sync): repo for repo in self.repositories}
            results = []

            for future in concurrent.futures.as_completed(futures):
                repo = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    logger.error(f"Error processing {repo.name}: {e}")
                    results.append(False)

            return results

    def process(self):
        """Process all repositories

        Returns:
            True if all repositories processed successfully
        """
        if not self.config:
            self.load()

        logger.info(f"Processing {len(self.repositories)} repositories")

        if self.max_workers > 1 and len(self.repositories) > 1:
            logger.info(f"Using parallel processing with {self.max_workers} workers")
            results = self.process_parallel()
        else:
            logger.info("Using sequential processing")
            results = self.process_sequential()

        success_count = sum(1 for r in results if r)
        logger.info(
            f"Processed {len(results)} repositories: "
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

        logger.info("Anchoring repository revisions to current commit SHAs")

        # Update repository configurations with current SHAs
        for repo in self.repositories:
            current_sha1 = repo.get_current_sha1()
            if current_sha1:
                # Find and update corresponding repository in configuration
                for repo_config in self.config["repositories"]:
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


def setup_arg_parser():
    """Setup argument parser"""
    parser = argparse.ArgumentParser(
        description="Clone and synchronize repositories as defined in gitfleet.json",
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
        fleet_path = os.path.join(current_dir, FleetManager.FLEET_CONFIG_NAME)

        if not os.path.exists(fleet_path):
            raise ConfigError(
                f"Cannot find {FleetManager.FLEET_CONFIG_NAME} in current directory"
            )

        # Initialize and process fleet
        fleet_manager = FleetManager(
            current_dir,
            args.force_shallow_clone,
            dry_run=args.dry_run,
            max_workers=args.parallel,
        )

        fleet_manager.process()

        # Handle anchoring if requested
        if args.anchor is not None:
            output_path = args.anchor or None
            fleet_manager.anchor(output_path)

        logger.info("All operations completed successfully!")
        return 0

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
