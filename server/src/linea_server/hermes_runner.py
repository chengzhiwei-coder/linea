from pathlib import Path

DEFAULT_PROFILE = "default"
DEFAULT_HERMES_LOG_ROOT = Path(".data/hermes_jobs")


def resolve_profile_home(profile: str | None = None, *, os_home: Path | None = None) -> Path:
    home = Path.home() if os_home is None else os_home
    profile_name = DEFAULT_PROFILE if profile is None else profile
    if profile_name == DEFAULT_PROFILE:
        return home
    return home / ".hermes" / "profiles" / profile_name / "home"


def build_hermes_prompt(task: str) -> str:
    return (
        f"{task}\n\n"
        "When you are done, send the final result to the Telegram home channel. "
        "Keep the delivered result concise and useful."
    )


def build_hermes_argv(prompt: str) -> list[str]:
    return ["hermes", "chat", "-Q", "-q", prompt]
