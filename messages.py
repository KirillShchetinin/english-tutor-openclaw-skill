from __future__ import annotations

# All user-facing Russian message constants live here.

# core/entry.py
ABSENCE_NUDGE = (
    "👋 Давно не занимались! "
    "Когда будешь готов — напиши, и мы продолжим."
)
NO_EXERCISES = (
    "📚 Занятие готово, "
    "но упражнений пока нет. "
    "Скоро добавим!"
)

# core/resume.py
NO_PENDING_SESSION = "Нет незавершённого занятия. Начни новое!"
SESSION_ERROR = "Занятие прервалось из-за ошибки. Начни новое!"
CLOSE_TO_NEXT_SESSION = "Скоро будет следующее занятие — подожди его!"
EXERCISE_UNAVAILABLE = "Упражнение больше недоступно. Начни новое занятие!"

# exercises/vocab.py
VOCAB_EMPTY = "Словарь пока пуст. Скоро добавим новые слова!"
VOCAB_HEADER = "📖 **Словарный запас**"
VOCAB_RECALL_HINT = "Попробуй вспомнить английские слова, прежде чем читать их!"

# exercises/vocab_test.py
VOCAB_TEST_HEADER = "✏️ **Проверка слов**\nНапиши английское слово по его переводу."
VOCAB_TEST_QUESTION = "({index}/{total}) Как по-английски **'{ru_word}'**?"
VOCAB_TEST_CORRECT = "Правильно! **{en_word}** ✅"
VOCAB_TEST_INCORRECT = "Не совсем. Правильный ответ: **{en_word}** (ты написал: {user_answer})"
VOCAB_TEST_SUMMARY = "Результат: {correct}/{total} правильно!"
VOCAB_TEST_EMPTY = "Пока нет слов для проверки. Скоро появятся!"
