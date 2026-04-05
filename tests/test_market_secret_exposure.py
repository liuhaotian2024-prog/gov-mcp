"""Market-Driven Experiment: Secret Exposure Prevention.

Market basis: Developer community's #1 AI agent security complaint is
secret file exposure (.env, credentials, API keys, SSH keys).

Hypothesis: gov-mcp with a well-designed default deny list can
intercept 100% of common secret file access patterns.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "Y-star-gov"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ystar import IntentContract, check

# Production-grade secret deny list
# FIXED: deny patterns must match how the kernel does substring matching.
# Kernel uses: pattern.lower() in v_str.lower()
# So ".env" matches any path containing ".env" (good).
# But "/.env" only matches paths containing "/.env" — misses bare ".env".
SECRET_DENY = IntentContract(
    deny=[
        # Environment files — use ".env" not "/.env" to catch all forms
        ".env",
        # SSH keys
        "/.ssh/",
        "/id_rsa",
        "/id_ed25519",
        # Cloud credentials
        "/.aws/",
        "/.gcloud/",
        "/.azure/",
        # Package manager tokens
        "/.npmrc",
        "/.pypirc",
        # Docker
        "/.docker/",
        # Git credentials
        "/.git-credentials",
        "/.netrc",
        # Kubernetes
        "/.kube/",
        # Database & secrets
        "credentials",  # Catches credentials.json, /credentials/, etc.
        "/secrets",     # Catches /secrets/ and secrets.yaml paths with /
        "private_key",
        "/.pgpass",
        # Additional patterns for completeness
        ".secrets",     # Dotfile secrets
        "tfstate",      # Terraform state (contains cloud creds)
        ".vault-token", # HashiCorp Vault
        "secret",       # Broad catch for paths containing "secret"
    ],
)


# 30 secret file patterns (comprehensive)
SECRET_FILES = [
    # Environment files (most common)
    ".env",
    ".env.local",
    ".env.production",
    ".env.staging",
    "config/.env",
    # SSH keys
    os.path.expanduser("~") + "/.ssh/id_rsa",
    os.path.expanduser("~") + "/.ssh/id_ed25519",
    os.path.expanduser("~") + "/.ssh/authorized_keys",
    # Cloud credentials
    os.path.expanduser("~") + "/.aws/credentials",
    os.path.expanduser("~") + "/.aws/config",
    os.path.expanduser("~") + "/.gcloud/application_default_credentials.json",
    os.path.expanduser("~") + "/.azure/accessTokens.json",
    # Package manager tokens
    os.path.expanduser("~") + "/.npmrc",
    os.path.expanduser("~") + "/.pypirc",
    # Docker
    os.path.expanduser("~") + "/.docker/config.json",
    # Git
    os.path.expanduser("~") + "/.git-credentials",
    os.path.expanduser("~") + "/.netrc",
    # Kubernetes
    os.path.expanduser("~") + "/.kube/config",
    # Database
    "./config/credentials.json",
    "./secrets/api_key.txt",
    "./private_key.pem",
    os.path.expanduser("~") + "/.pgpass",
    # Application secrets
    "./config/secrets.yaml",
    "./credentials/service_account.json",
    "./.secrets",
    # Less obvious but dangerous
    "./terraform.tfstate",  # Contains cloud credentials
    "./.vault-token",
    "./config/private_key.pem",
    "./deploy/secrets/db.conf",
    "production/secrets/master.key",
]

# 15 safe files that should NOT be blocked
SAFE_FILES = [
    "./src/main.py",
    "./src/config/settings.py",  # Config but not secrets
    "./README.md",
    "./tests/test_auth.py",  # Tests about auth but not real secrets
    "./docs/security.md",  # Docs about security
    "./src/utils/crypto.py",  # Crypto code, not credentials
    "./public/index.html",
    "./src/api/routes.py",
    "./package.json",
    "./requirements.txt",
    "./Dockerfile",
    "./src/database/migrations/001.sql",
    "./src/auth/oauth.py",
    "./tests/conftest.py",
    "./src/core/engine.py",
]


def test_all_secrets_blocked():
    """Every secret file pattern must be DENY."""
    failures = []
    for i, path in enumerate(SECRET_FILES):
        r = check(params={"tool_name": "Read", "file_path": path},
                  result={}, contract=SECRET_DENY)
        if r.passed:
            failures.append(f"#{i+1} ALLOWED: {path}")

    if failures:
        print(f"\n  SECRET EXPOSURE GAPS:")
        for f in failures:
            print(f"    {f}")

    blocked = len(SECRET_FILES) - len(failures)
    rate = blocked / len(SECRET_FILES) * 100
    print(f"\n  Secret interception: {blocked}/{len(SECRET_FILES)} ({rate:.0f}%)")

    assert len(failures) == 0, (
        f"{len(failures)} secret files ALLOWED through:\n" + "\n".join(failures)
    )


def test_safe_files_not_blocked():
    """Safe files must NOT be blocked (false positive check)."""
    false_positives = []
    for path in SAFE_FILES:
        r = check(params={"tool_name": "Read", "file_path": path},
                  result={}, contract=SECRET_DENY)
        if not r.passed:
            false_positives.append(f"BLOCKED: {path}")

    if false_positives:
        print(f"\n  FALSE POSITIVES:")
        for f in false_positives:
            print(f"    {f}")

    assert len(false_positives) == 0, (
        f"{len(false_positives)} safe files incorrectly blocked:\n"
        + "\n".join(false_positives)
    )


def test_deny_list_completeness():
    """The deny list covers all major secret categories."""
    categories = {
        "env_files": any("env" in d.lower() for d in SECRET_DENY.deny),
        "ssh_keys": any("ssh" in d.lower() or "id_rsa" in d.lower() for d in SECRET_DENY.deny),
        "cloud_creds": any("aws" in d.lower() or "gcloud" in d.lower() for d in SECRET_DENY.deny),
        "pkg_tokens": any("npmrc" in d.lower() or "pypirc" in d.lower() for d in SECRET_DENY.deny),
        "docker": any("docker" in d.lower() for d in SECRET_DENY.deny),
        "git_creds": any("git-credentials" in d.lower() or "netrc" in d.lower() for d in SECRET_DENY.deny),
        "k8s": any("kube" in d.lower() for d in SECRET_DENY.deny),
        "database": any("credentials" in d.lower() or "pgpass" in d.lower() for d in SECRET_DENY.deny),
    }

    print(f"\n  Secret categories covered:")
    for cat, covered in categories.items():
        print(f"    {'✓' if covered else '✗'} {cat}")

    assert all(categories.values()), f"Missing categories: {[k for k,v in categories.items() if not v]}"
