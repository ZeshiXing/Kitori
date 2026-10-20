"""Settings-panel localization, independent of the speech-recognition language."""
import json
from functools import lru_cache
from pathlib import Path
import re

from .settings import read_json, write_json

UI_LANGUAGES = ('zh', 'ja', 'en')
CATALOG = json.loads(Path(__file__).with_name('ui_translations.json').read_text(encoding='utf-8'))


def load_ui_language(root):
    language = read_json(Path(root) / 'config/ui.json').get('language', 'zh')
    return language if language in UI_LANGUAGES else 'zh'


def save_ui_language(root, language):
    if language not in UI_LANGUAGES:
        raise ValueError('Unsupported interface language')
    path = Path(root) / 'config/ui.json'
    values = read_json(path)
    write_json(path, {**values, 'language': language})


def install_qt_language(language):
    """Reuse Qt's own translations for standard color/font dialog controls."""
    from PySide6.QtCore import QCoreApplication, QLibraryInfo, QLocale, QTranslator
    app = QCoreApplication.instance()
    previous = getattr(app, '_caption_qt_translator', None)
    if previous:
        app.removeTranslator(previous)
        previous.deleteLater()
    translator = QTranslator(app)
    locale = {'zh':'zh_CN','ja':'ja','en':'en'}[language]
    QLocale.setDefault(QLocale(locale))
    if translator.load('qtbase_' + locale, QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)
    app._caption_qt_translator = translator


@lru_cache(maxsize=4)
def _reverse(language):
    return {row[language]: source for source, row in CATALOG.items()}


@lru_cache(maxsize=8)
def _pattern(language, reverse):
    mapping = _reverse(language) if reverse else CATALOG
    return re.compile('|'.join(re.escape(key) for key in sorted(mapping, key=len, reverse=True)))


def translate(text, language='zh', source_language='zh'):
    """Translate UI-only labels and composed status text, never recognition data.

    Longest phrases match first in one substitution, so replacement text is not
    translated a second time. Reversing the previous panel language lets Qt
    controls be relabeled in place without reconstructing the dialog.
    """
    if language not in UI_LANGUAGES:
        language = 'zh'
    if source_language in ('ja', 'en'):
        reverse = _reverse(source_language)
        text = _pattern(source_language, True).sub(lambda match: reverse[match[0]], text)
    if language == 'zh':
        return text
    return _pattern(language, False).sub(lambda match: CATALOG[match[0]][language], text)
