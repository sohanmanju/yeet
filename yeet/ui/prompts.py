"""Directory completion for the cleanup journey."""

from __future__ import annotations

import os

from prompt_toolkit.completion import Completer, Completion


class PathCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = os.path.expanduser(document.text_before_cursor) or "/"
        complete_directory = os.path.isdir(text)
        search_dir = text if complete_directory else os.path.dirname(text) or "."
        prefix = "" if complete_directory else os.path.basename(text)
        entries = []
        try:
            with os.scandir(search_dir) as iterator:
                for entry in iterator:
                    try:
                        if (
                            not entry.name.startswith(".")
                            and entry.is_dir()
                            and entry.name.lower().startswith(prefix.lower())
                        ):
                            entries.append(entry.name)
                    except OSError:
                        continue
        except OSError:
            return
        for name in sorted(entries, key=str.lower)[:50]:
            yield Completion(
                name + "/",
                start_position=-len(prefix),
                display=name + "/",
                display_meta="dir",
            )
