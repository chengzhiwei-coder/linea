from linea_server.hermes_runner import build_hermes_argv, build_hermes_prompt, resolve_profile_home


def test_resolve_profile_home_returns_os_home_for_default_profile(tmp_path):
    assert resolve_profile_home(None, os_home=tmp_path) == tmp_path
    assert resolve_profile_home("default", os_home=tmp_path) == tmp_path


def test_resolve_profile_home_returns_named_profile_home_under_hermes_profiles(tmp_path):
    assert (
        resolve_profile_home("programmer", os_home=tmp_path)
        == tmp_path / ".hermes" / "profiles" / "programmer" / "home"
    )


def test_build_hermes_prompt_contains_task_delivery_instruction_and_concision_guidance():
    prompt = build_hermes_prompt("Do X")

    assert "Do X" in prompt
    assert "send the final result to the Telegram home channel" in prompt
    assert "Keep the delivered result concise and useful." in prompt


def test_build_hermes_prompt_does_not_inject_linea_or_server_paths():
    prompt = build_hermes_prompt("Do X")

    assert "/home/singleton/linea" not in prompt
    assert "server/src" not in prompt


def test_build_hermes_prompt_preserves_linea_or_server_paths_from_caller_task():
    task = "Inspect /home/singleton/linea and server/src when explicitly requested."

    prompt = build_hermes_prompt(task)

    assert "/home/singleton/linea" in prompt
    assert "server/src" in prompt


def test_build_hermes_argv_passes_prompt_as_argv_argument():
    prompt = build_hermes_prompt("Do X")

    assert build_hermes_argv(prompt) == ["hermes", "chat", "-Q", "-q", prompt]
