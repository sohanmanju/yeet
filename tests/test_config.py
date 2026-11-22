"""Configuration persistence through the user-facing TOML format."""

from yeet.config import Config


def test_all_settings_round_trip_with_quoted_unicode_paths(tmp_path):
    config = Config(
        start_path='~/Projects/"quoted"/日本語',
        min_size_mb=17,
        show_hidden=False,
        use_trash=False,
        confirm_delete=False,
        color_enabled=False,
        days_threshold=32,
        large_file_mb=81,
        cache_size_mb=7,
        cache_enabled=False,
        cache_max_age_hours=3,
        protected_paths=['~/keep/"important"'],
        ignored_paths=["~/cache\\old"],
        bookmarks=["~/日本語", '~/Projects/"quoted"'],
    )
    path = tmp_path / "settings.toml"
    assert config.save(path)
    assert Config.load(path) == config


def test_missing_and_malformed_config_use_defaults(tmp_path):
    path = tmp_path / "settings.toml"
    assert Config.load(path) == Config()
    path.write_text("[explorer\ninvalid")
    assert Config.load(path) == Config()


def test_partial_config_preserves_unspecified_defaults(tmp_path):
    path = tmp_path / "settings.toml"
    path.write_text("[cache]\nenabled = false\n[explorer]\nmin_size_mb = 12\n")
    assert Config.load(path) == Config(cache_enabled=False, min_size_mb=12)
