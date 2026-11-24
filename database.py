"""Слой работы с PostgreSQL. Все SQL-запросы — здесь."""

import psycopg2
from psycopg2.extras import RealDictCursor

from config import DB_CONFIG, COMMON_WORDS


def get_db_connection():
    """Подключение к PostgreSQL."""
    return psycopg2.connect(**DB_CONFIG)


def init_database():
    """Создать таблицы (если нет) и заполнить общие слова один раз."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(100) UNIQUE NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS common_words (
                    id SERIAL PRIMARY KEY,
                    russian_word VARCHAR(255) NOT NULL,
                    english_word VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS user_words (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    russian_word VARCHAR(255) NOT NULL,
                    english_word VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS learning_stats (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    word_id INTEGER NOT NULL,
                    word_type VARCHAR(10) NOT NULL CHECK (word_type IN ('common', 'personal')),
                    correct_answers INTEGER DEFAULT 0,
                    total_attempts INTEGER DEFAULT 0,
                    last_reviewed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, word_id, word_type)
                );

                CREATE INDEX IF NOT EXISTS idx_user_words_user_id ON user_words(user_id);
                CREATE INDEX IF NOT EXISTS idx_learning_stats_user_id ON learning_stats(user_id);
            """)

            cur.execute("SELECT COUNT(*) FROM common_words")
            if cur.fetchone()[0] == 0:
                cur.executemany(
                    "INSERT INTO common_words (russian_word, english_word) VALUES (%s, %s)",
                    COMMON_WORDS,
                )
        conn.commit()
    finally:
        conn.close()


def login_user(username):
    """Вернуть id пользователя или создать нового."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE username = %s", (username,))
            row = cur.fetchone()
            if row:
                return row[0]
            cur.execute(
                "INSERT INTO users (username) VALUES (%s) RETURNING id",
                (username,),
            )
            user_id = cur.fetchone()[0]
        conn.commit()
        return user_id
    finally:
        conn.close()


def get_user_words(user_id):
    """Все доступные пользователю слова: общие + личные."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, russian_word, english_word, 'common' AS word_type
                FROM common_words
                UNION ALL
                SELECT id, russian_word, english_word, 'personal' AS word_type
                FROM user_words
                WHERE user_id = %s
            """, (user_id,))
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def add_personal_word(user_id, russian_word, english_word):
    """Добавить персональное слово, если такого ещё нет."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 1 FROM user_words
                WHERE user_id = %s AND LOWER(russian_word) = LOWER(%s)
            """, (user_id, russian_word.strip()))
            if cur.fetchone():
                return False

            cur.execute("""
                INSERT INTO user_words (user_id, russian_word, english_word)
                VALUES (%s, %s, %s)
            """, (user_id, russian_word.strip(), english_word.strip()))
        conn.commit()
        return True
    finally:
        conn.close()


def delete_personal_word(user_id, word_id):
    """Удалить персональное слово (только своё)."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM user_words WHERE id = %s AND user_id = %s RETURNING id",
                (word_id, user_id),
            )
            deleted = cur.fetchone() is not None
        conn.commit()
        return deleted
    finally:
        conn.close()


def update_stats(user_id, word_id, word_type, is_correct):
    """Обновить статистику по слову (UPSERT)."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO learning_stats
                    (user_id, word_id, word_type, correct_answers, total_attempts, last_reviewed)
                VALUES (%s, %s, %s, %s, 1, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id, word_id, word_type)
                DO UPDATE SET
                    correct_answers = learning_stats.correct_answers + EXCLUDED.correct_answers,
                    total_attempts  = learning_stats.total_attempts + 1,
                    last_reviewed   = CURRENT_TIMESTAMP
            """, (user_id, word_id, word_type, 1 if is_correct else 0))
        conn.commit()
    finally:
        conn.close()


def get_statistics(user_id):
    """Статистика пользователя: сводка + последние попытки."""
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    COALESCE(SUM(total_attempts), 0)  AS total_attempts,
                    COALESCE(SUM(correct_answers), 0) AS correct_answers,
                    COUNT(*)                           AS unique_words_studied
                FROM learning_stats
                WHERE user_id = %s
            """, (user_id,))
            summary = dict(cur.fetchone())
            summary["accuracy"] = (
                round(summary["correct_answers"] / summary["total_attempts"] * 100, 1)
                if summary["total_attempts"] else 0
            )

            cur.execute("""
                SELECT
                    COALESCE(cw.russian_word, uw.russian_word) AS russian_word,
                    COALESCE(cw.english_word, uw.english_word) AS english_word,
                    ls.word_type,
                    ls.correct_answers,
                    ls.total_attempts,
                    ls.last_reviewed
                FROM learning_stats ls
                LEFT JOIN common_words cw
                    ON ls.word_type = 'common' AND cw.id = ls.word_id
                LEFT JOIN user_words uw
                    ON ls.word_type = 'personal' AND uw.id = ls.word_id
                WHERE ls.user_id = %s
                ORDER BY ls.last_reviewed DESC
                LIMIT 20
            """, (user_id,))
            summary["history"] = [dict(r) for r in cur.fetchall()]
            return summary
    finally:
        conn.close()
