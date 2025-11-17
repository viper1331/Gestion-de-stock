"""Service de mise à jour automatique depuis GitHub."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from backend.core.db import DATA_DIR


class UpdateError(RuntimeError):
    """Erreur générique pour les opérations de mise à jour."""


class UpdateConfigurationError(UpdateError):
    """Erreur déclenchée lorsque la configuration GitHub est invalide."""


class UpdateExecutionError(UpdateError):
    """Erreur déclenchée lorsqu'une commande système échoue."""


@dataclass(frozen=True)
class PullRequestData:
    """Informations minimales sur un pull request GitHub."""

    number: int
    title: str
    url: str
    merged_at: datetime | None
    head_sha: str


@dataclass(frozen=True)
class UpdateState:
    """État persistant de la dernière mise à jour déployée."""

    last_deployed_pull: int | None = None
    last_deployed_sha: str | None = None
    last_deployed_at: datetime | None = None
    previous_deployed_pull: int | None = None
    previous_deployed_sha: str | None = None
    previous_deployed_at: datetime | None = None


@dataclass(frozen=True)
class UpdateStatusData:
    """Représentation interne de l'état de mise à jour du serveur."""

    repository: str
    branch: str
    current_commit: str | None
    latest_pull_request: PullRequestData | None
    last_deployed_pull: int | None
    last_deployed_sha: str | None
    last_deployed_at: datetime | None
    pending_update: bool
    previous_deployed_pull: int | None
    previous_deployed_sha: str | None
    previous_deployed_at: datetime | None
    can_revert: bool

    def to_dict(self) -> dict[str, Any]:
        """Convertit l'état en dictionnaire sérialisable."""

        def _serialize_pr(pr: PullRequestData | None) -> dict[str, Any] | None:
            if pr is None:
                return None
            payload = asdict(pr)
            if pr.merged_at is not None:
                payload["merged_at"] = pr.merged_at
            return payload

        payload = {
            "repository": self.repository,
            "branch": self.branch,
            "current_commit": self.current_commit,
            "latest_pull_request": _serialize_pr(self.latest_pull_request),
            "last_deployed_pull": self.last_deployed_pull,
            "last_deployed_sha": self.last_deployed_sha,
            "last_deployed_at": self.last_deployed_at,
            "previous_deployed_pull": self.previous_deployed_pull,
            "previous_deployed_sha": self.previous_deployed_sha,
            "previous_deployed_at": self.previous_deployed_at,
            "pending_update": self.pending_update,
            "can_revert": self.can_revert,
        }
        return payload


@dataclass(frozen=True)
class UpdateSettings:
    """Paramètres requis pour accéder au dépôt GitHub."""

    owner: str
    repository: str
    branch: str
    token: str | None = None

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repository}"


_STATE_FILE = DATA_DIR / "update_state.json"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_GITHUB_API_URL = "https://api.github.com"


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_state() -> UpdateState:
    if not _STATE_FILE.exists():
        return UpdateState()
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as buffer:
            payload = json.load(buffer)
    except (OSError, json.JSONDecodeError) as exc:
        raise UpdateExecutionError("Impossible de lire le fichier d'état des mises à jour") from exc
    return UpdateState(
        last_deployed_pull=payload.get("last_deployed_pull"),
        last_deployed_sha=payload.get("last_deployed_sha"),
        last_deployed_at=_parse_datetime(payload.get("last_deployed_at")),
        previous_deployed_pull=payload.get("previous_deployed_pull"),
        previous_deployed_sha=payload.get("previous_deployed_sha"),
        previous_deployed_at=_parse_datetime(payload.get("previous_deployed_at")),
    )


def _save_state(state: UpdateState) -> None:
    payload = {
        "last_deployed_pull": state.last_deployed_pull,
        "last_deployed_sha": state.last_deployed_sha,
        "last_deployed_at": state.last_deployed_at.isoformat() if state.last_deployed_at else None,
        "previous_deployed_pull": state.previous_deployed_pull,
        "previous_deployed_sha": state.previous_deployed_sha,
        "previous_deployed_at": state.previous_deployed_at.isoformat() if state.previous_deployed_at else None,
    }
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(_STATE_FILE, "w", encoding="utf-8") as buffer:
            json.dump(payload, buffer, ensure_ascii=False, indent=2)
    except OSError as exc:
        raise UpdateExecutionError("Impossible d'écrire le fichier d'état des mises à jour") from exc


def _normalize_slug(slug: str) -> str:
    slug = slug.strip()
    if slug.endswith(".git"):
        slug = slug[:-4]
    if "/" not in slug:
        raise UpdateConfigurationError(
            "La variable GITHUB_REPOSITORY doit être au format 'propriétaire/référentiel'."
        )
    owner, repository = slug.split("/", 1)
    owner = owner.strip()
    repository = repository.strip()
    if not owner or not repository:
        raise UpdateConfigurationError(
            "La variable GITHUB_REPOSITORY doit contenir un propriétaire et un dépôt valides."
        )
    return f"{owner}/{repository}"


def _slug_from_git_remote() -> str:
    try:
        remote_url = _run_git_command("config", "--get", "remote.origin.url")
    except UpdateExecutionError as exc:
        raise UpdateConfigurationError(
            "Impossible de déterminer le dépôt GitHub. Définissez la variable GITHUB_REPOSITORY."
        ) from exc

    remote_url = remote_url.strip()
    if remote_url.endswith(".git"):
        remote_url = remote_url[:-4]

    if remote_url.startswith("git@"):
        _, _, path = remote_url.partition(":")
    elif remote_url.startswith(("https://", "http://", "ssh://", "git://")):
        parsed = urlparse(remote_url)
        path = parsed.path.strip("/")
        if not path:
            raise UpdateConfigurationError(
                "Impossible d'interpréter l'URL du dépôt Git configuré. Définissez GITHUB_REPOSITORY."
            )
        segments = [segment for segment in path.split("/") if segment]
        if len(segments) < 2:
            raise UpdateConfigurationError(
                "Impossible d'interpréter l'URL du dépôt Git configuré. Définissez GITHUB_REPOSITORY."
            )
        path = "/".join(segments[-2:])
    else:
        path = remote_url

    path = path.strip("/")
    if "/" not in path:
        raise UpdateConfigurationError(
            "Impossible d'interpréter l'URL du dépôt Git configuré. Définissez GITHUB_REPOSITORY."
        )
    return _normalize_slug(path)


def _detect_branch(default: str = "main") -> str:
    try:
        branch = _run_git_command("rev-parse", "--abbrev-ref", "HEAD")
    except UpdateExecutionError:
        return default
    branch = branch.strip()
    return branch or default


def _get_settings() -> UpdateSettings:
    slug_env = os.getenv("GITHUB_REPOSITORY")
    if slug_env:
        slug = _normalize_slug(slug_env)
    else:
        slug = _slug_from_git_remote()

    owner, repository = slug.split("/", 1)

    branch = os.getenv("GITHUB_BRANCH")
    if branch:
        branch = branch.strip()
    if not branch:
        branch = _detect_branch()

    token = os.getenv("GITHUB_TOKEN")
    return UpdateSettings(owner=owner, repository=repository, branch=branch, token=token)


def _run_git_command(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=_REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise UpdateExecutionError("La commande 'git' est introuvable sur le serveur") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else ""
        stdout = exc.stdout.strip() if exc.stdout else ""
        message = stderr or stdout or str(exc)
        raise UpdateExecutionError(f"Échec de la commande git {' '.join(args)}: {message}") from exc
    return result.stdout.strip()


def _current_commit() -> str | None:
    try:
        return _run_git_command("rev-parse", "HEAD")
    except UpdateExecutionError:
        return None


def _build_status(
    settings: UpdateSettings,
    state: UpdateState,
    latest: PullRequestData | None,
    current_commit: str | None,
) -> UpdateStatusData:
    pending = False
    if latest is not None:
        if state.last_deployed_pull is None or state.last_deployed_sha is None:
            pending = True
        else:
            pending = (
                state.last_deployed_pull != latest.number
                or state.last_deployed_sha != latest.head_sha
            )
    return UpdateStatusData(
        repository=settings.slug,
        branch=settings.branch,
        current_commit=current_commit,
        latest_pull_request=latest,
        last_deployed_pull=state.last_deployed_pull,
        last_deployed_sha=state.last_deployed_sha,
        last_deployed_at=state.last_deployed_at,
        previous_deployed_pull=state.previous_deployed_pull,
        previous_deployed_sha=state.previous_deployed_sha,
        previous_deployed_at=state.previous_deployed_at,
        pending_update=pending,
        can_revert=state.previous_deployed_sha is not None,
    )


async def _fetch_latest_merged_pull(settings: UpdateSettings) -> PullRequestData | None:
    url = f"{_GITHUB_API_URL}/repos/{settings.slug}/pulls"
    params = {
        "state": "closed",
        "per_page": 10,
        "sort": "updated",
        "direction": "desc",
    }
    headers = {"Accept": "application/vnd.github+json"}
    if settings.token:
        headers["Authorization"] = f"Bearer {settings.token}"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
            response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.json().get("message") if exc.response.content else str(exc)
        raise UpdateExecutionError(f"Échec de la récupération des pull requests GitHub: {detail}") from exc
    except httpx.HTTPError as exc:
        raise UpdateExecutionError("Erreur réseau lors de l'accès à GitHub") from exc

    for item in response.json():
        merged_at = item.get("merged_at")
        if not merged_at:
            continue
        head_sha = item.get("merge_commit_sha") or item.get("head", {}).get("sha")
        if not head_sha:
            continue
        return PullRequestData(
            number=int(item["number"]),
            title=str(item.get("title", "")),
            url=str(item.get("html_url", "")),
            merged_at=_parse_datetime(merged_at),
            head_sha=str(head_sha),
        )
    return None


async def get_status() -> UpdateStatusData:
    settings = _get_settings()
    state = _load_state()
    latest = await _fetch_latest_merged_pull(settings)
    current_commit = _current_commit()
    return _build_status(settings, state, latest, current_commit)


async def apply_latest_update() -> tuple[bool, UpdateStatusData]:
    settings = _get_settings()
    state = _load_state()
    latest = await _fetch_latest_merged_pull(settings)
    current_commit = _current_commit()

    if latest is None:
        status = _build_status(settings, state, latest, current_commit)
        return False, status

    if (
        state.last_deployed_pull == latest.number
        and state.last_deployed_sha == latest.head_sha
    ):
        status = _build_status(settings, state, latest, current_commit)
        return False, status

    _run_git_command("fetch", "origin", settings.branch)
    _run_git_command("checkout", settings.branch)
    _run_git_command("pull", "--ff-only", "origin", settings.branch)

    previous_sha = state.last_deployed_sha or current_commit
    previous_at = state.last_deployed_at

    new_state = UpdateState(
        last_deployed_pull=latest.number,
        last_deployed_sha=latest.head_sha,
        last_deployed_at=_now(),
        previous_deployed_pull=state.last_deployed_pull,
        previous_deployed_sha=previous_sha,
        previous_deployed_at=previous_at,
    )
    _save_state(new_state)
    new_commit = _current_commit()
    status = _build_status(settings, new_state, latest, new_commit)
    return True, status


async def revert_last_update() -> tuple[bool, UpdateStatusData]:
    """Restaure la version précédente déployée si elle est disponible."""

    settings = _get_settings()
    state = _load_state()
    latest = await _fetch_latest_merged_pull(settings)
    current_commit = _current_commit()

    if state.previous_deployed_sha is None:
        status = _build_status(settings, state, latest, current_commit)
        return False, status

    target_pull = state.previous_deployed_pull
    target_sha = state.previous_deployed_sha
    target_at = state.previous_deployed_at or _now()

    _run_git_command("checkout", settings.branch)
    _run_git_command("fetch", "origin", settings.branch)
    _run_git_command("reset", "--hard", target_sha)

    new_state = UpdateState(
        last_deployed_pull=target_pull,
        last_deployed_sha=target_sha,
        last_deployed_at=target_at,
        previous_deployed_pull=state.last_deployed_pull,
        previous_deployed_sha=state.last_deployed_sha,
        previous_deployed_at=state.last_deployed_at,
    )
    _save_state(new_state)
    reverted_commit = _current_commit()
    status = _build_status(settings, new_state, latest, reverted_commit)
    return True, status
