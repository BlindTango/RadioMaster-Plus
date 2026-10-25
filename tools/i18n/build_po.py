"""Build <lang>/LC_MESSAGES/radiomaster.po from a compact translation list.

    python tools/i18n/build_po.py list            # numbered English strings
    python tools/i18n/build_po.py build fr fr.txt # fr.txt: lines "N|translation"

The English strings and their order come from the Spanish catalogue, which is
the reference. Missing numbers stay untranslated (the app falls back to English).
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
I18N = os.path.join(HERE, "..", "..", "src", "radiomaster", "i18n")
sys.path.insert(0, os.path.join(HERE, "..", "..", "src"))

from radiomaster.i18n.po import parse_po  # noqa: E402

HEADERS = {"fr": "French", "de": "German", "it": "Italian", "pt": "Portuguese",
           "ru": "Russian", "ja": "Japanese", "zh": "Chinese (Simplified)"}


def reference() -> list[str]:
    return list(parse_po(os.path.join(I18N, "es", "LC_MESSAGES", "radiomaster.po")))


def quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def main() -> None:
    ids = reference()
    if sys.argv[1] == "list":
        for n, text in enumerate(ids, 1):
            print(f"{n}|{text}")
        return
    lang, source = sys.argv[2], sys.argv[3]
    done: dict[int, str] = {}
    with open(source, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if "|" in line:
                number, _, text = line.partition("|")
                if number.strip().isdigit():
                    done[int(number)] = text.replace("\\n", "\n")
    out = [f"# {HEADERS.get(lang, lang)} translation for RadioMaster+.",
           "# Unreviewed draft: wording may need review by a native speaker.",
           'msgid ""', 'msgstr ""', '"Project-Id-Version: RadioMaster+\\n"',
           f'"Language: {lang}\\n"', '"MIME-Version: 1.0\\n"',
           '"Content-Type: text/plain; charset=UTF-8\\n"', ""]
    for n, english in enumerate(ids, 1):
        if n in done and done[n].strip():
            out += [f"msgid {quote(english)}", f"msgstr {quote(done[n])}"]
    folder = os.path.join(I18N, lang, "LC_MESSAGES")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "radiomaster.po"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(out) + "\n")
    print(f"{lang}: {len(done)} of {len(ids)} strings")


if __name__ == "__main__":
    main()
