"""
EnglishCard - Приложение для изучения английского языка
Streamlit + PostgreSQL
"""

import random
import pandas as pd
import streamlit as st

from config import WELCOME_TEXT
from database import (
    init_database,
    login_user,
    get_user_words,
    add_personal_word,
    delete_personal_word,
    update_stats,
    get_statistics,
    get_db_connection,
)

# ============================================================
# НАСТРОЙКА СТРАНИЦЫ
# ============================================================
st.set_page_config(
    page_title="EnglishCard - Изучение английского",
    page_icon="📚",
    layout="wide",
)


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def generate_options(correct_word, all_words):
    """4 варианта ответа: 1 правильный + 3 случайных без дублей."""
    from config import FALLBACK_OPTIONS

    others = [w["english_word"] for w in all_words if w["english_word"] != correct_word]
    random.shuffle(others)

    if len(others) >= 3:
        wrongs = others[:3]
    else:
        wrongs = others + random.sample(FALLBACK_OPTIONS, 3 - len(others))

    options = wrongs + [correct_word]
    random.shuffle(options)
    return options


# ============================================================
# ИНТЕРФЕЙС
# ============================================================

def render_sidebar():
    """Боковая панель с авторизацией."""
    with st.sidebar:
        st.header("👤 Пользователь")

        if st.session_state.user_id is None:
            username = st.text_input("Введите ваше имя", key="login_input")
            if st.button("Войти", type="primary", use_container_width=True):
                if username.strip():
                    user_id = login_user(username.strip())
                    st.session_state.user_id = user_id
                    st.session_state.username = username.strip()
                    st.rerun()
                else:
                    st.warning("Имя не может быть пустым")
        else:
            st.success(f"Вы вошли как **{st.session_state.username}**")
            if st.button("🚪 Выйти", use_container_width=True):
                st.session_state.clear()
                st.rerun()


def render_study_tab(words):
    """Вкладка изучения: слово на русском + 4 кнопки-варианта."""
    if not words:
        st.info("Нет доступных слов. Добавьте что-нибудь во вкладке ➕")
        return

    if (
        "current_word" not in st.session_state
        or st.session_state.current_word is None
        or st.session_state.get("need_new_word", False)
    ):
        st.session_state.current_word = random.choice(words)
        st.session_state.options = generate_options(
            st.session_state.current_word["english_word"], words
        )
        st.session_state.answered = None
        st.session_state.need_new_word = False

    w = st.session_state.current_word
    st.subheader("📖 Как переводится это слово?")
    st.markdown(f"## **{w['russian_word']}**")
    st.caption(
        "Тип слова: "
        + ("общее" if w["word_type"] == "common" else "личное")
    )

    st.write("")

    if st.session_state.answered is not None:
        if st.session_state.answered == "correct":
            st.success(f"✅ Верно! **{w['russian_word']}** = **{w['english_word']}**")
        else:
            st.error(
                f"❌ Неправильно. Попробуй ещё раз!\n\n"
                f"Правильный ответ: **{w['english_word']}**"
            )

        if st.button("Следующее слово ▶️", type="primary", use_container_width=True):
            st.session_state.need_new_word = True
            st.rerun()
        return

    cols = st.columns(2)
    for i, opt in enumerate(st.session_state.options):
        with cols[i % 2]:
            if st.button(opt, key=f"opt_{i}", use_container_width=True):
                is_correct = (opt == w["english_word"])
                update_stats(
                    st.session_state.user_id,
                    w["id"],
                    w["word_type"],
                    is_correct,
                )
                st.session_state.answered = "correct" if is_correct else "wrong"
                st.rerun()


def render_add_word_tab():
    """Вкладка добавления персонального слова."""
    st.subheader("➕ Добавить новое слово")
    st.caption("Новое слово появится только в вашем словаре.")

    with st.form("add_word_form", clear_on_submit=True):
        russian = st.text_input("Слово на русском")
        english = st.text_input("Перевод на английский")
        submitted = st.form_submit_button("Добавить", type="primary")

    if submitted:
        if not russian.strip() or not english.strip():
            st.warning("Заполните оба поля")
        else:
            ok = add_personal_word(
                st.session_state.user_id, russian, english
            )
            if ok:
                st.success(f"✅ Слово **{russian}** → **{english}** добавлено")
            else:
                st.warning("Такое слово уже есть в вашем словаре")


def render_delete_word_tab(words):
    """Вкладка удаления персонального слова."""
    st.subheader("🗑️ Удалить слово")
    st.caption("Удалять можно только свои (личные) слова.")

    personal = [w for w in words if w["word_type"] == "personal"]
    if not personal:
        st.info("У вас пока нет личных слов для удаления.")
        return

    options_map = {
        f"{w['russian_word']} → {w['english_word']}": w["id"] for w in personal
    }
    choice = st.selectbox("Выберите слово", list(options_map.keys()))

    if st.button("Удалить", type="primary"):
        word_id = options_map[choice]
        ok = delete_personal_word(st.session_state.user_id, word_id)
        if ok:
            st.success(f"Слово **{choice}** удалено")
            if (
                "current_word" in st.session_state
                and st.session_state.current_word
                and st.session_state.current_word["id"] == word_id
                and st.session_state.current_word["word_type"] == "personal"
            ):
                st.session_state.current_word = None
            st.rerun()
        else:
            st.error("Не удалось удалить слово")


def render_statistics_tab(user_id):
    """Вкладка статистики."""
    st.subheader("📊 Ваша статистика")
    stats = get_statistics(user_id)

    col1, col2, col3 = st.columns(3)
    col1.metric("Всего попыток", stats["total_attempts"])
    col2.metric("Правильных ответов", stats["correct_answers"])
    col3.metric("Точность", f"{stats['accuracy']} %")

    st.markdown(f"**Изучено уникальных слов:** {stats['unique_words_studied']}")
    st.divider()

    st.markdown("### 📜 Последние попытки")
    if stats["history"]:
        df = pd.DataFrame(stats["history"])
        df = df.rename(columns={
            "russian_word": "Русский",
            "english_word": "Английский",
            "word_type": "Тип",
            "correct_answers": "Правильно",
            "total_attempts": "Попыток",
            "last_reviewed": "Когда",
        })
        df["Тип"] = df["Тип"].map({"common": "общее", "personal": "личное"})
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Пока нет данных. Начните тренировку во вкладке 📖")


def render_schema():
    """Отображение схемы БД + живая выборка из information_schema."""
    st.subheader("🗄️ Схема базы данных")

    st.markdown("""
    **users** — пользователи
    - `id` SERIAL PK
    - `username` VARCHAR(100) UNIQUE
    - `created_at` TIMESTAMP

    **common_words** — общие слова (доступны всем)
    - `id` SERIAL PK
    - `russian_word`, `english_word` VARCHAR(255)
    - `created_at` TIMESTAMP

    **user_words** — персональные слова
    - `id` SERIAL PK
    - `user_id` FK → users(id) ON DELETE CASCADE
    - `russian_word`, `english_word` VARCHAR(255)
    - `created_at` TIMESTAMP

    **learning_stats** — статистика по словам
    - `id` SERIAL PK
    - `user_id` FK → users(id) ON DELETE CASCADE
    - `word_id` INTEGER
    - `word_type` VARCHAR(10) — `common` / `personal`
    - `correct_answers`, `total_attempts` INTEGER
    - `last_reviewed` TIMESTAMP
    - UNIQUE(`user_id`, `word_id`, `word_type`)
    """)

    st.divider()
    st.markdown("### 📋 Живая структура таблиц")
    try:
        conn = get_db_connection()
        query = """
            SELECT table_name, column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name IN ('users', 'common_words', 'user_words', 'learning_stats')
            ORDER BY table_name, ordinal_position
        """
        df = pd.read_sql(query, conn)
        conn.close()

        table = st.selectbox("Выберите таблицу", sorted(df["table_name"].unique()))
        st.dataframe(
            df[df["table_name"] == table].drop(columns=["table_name"]),
            use_container_width=True,
            hide_index=True,
        )
    except Exception as e:
        st.error(f"Не удалось прочитать схему: {e}")


# ============================================================
# ГЛАВНАЯ ФУНКЦИЯ
# ============================================================

def main():
    # --- Инициализация состояния сессии ---
    defaults = {
        "user_id": None,
        "username": None,
        "current_word": None,
        "options": [],
        "answered": None,
        "need_new_word": False,
        "welcome_shown": False,
    }
    for key, val in defaults.items():
        st.session_state.setdefault(key, val)

    # --- Инициализация БД (один раз за сессию) ---
    if "db_initialized" not in st.session_state:
        try:
            init_database()
            st.session_state.db_initialized = True
        except Exception as e:
            st.error(f"❌ Не удалось подключиться к БД: {e}")
            st.info(
                "Проверьте, что PostgreSQL запущен и база `english_card` создана. "
                "Параметры подключения — в файле `config.py`."
            )
            st.stop()

    # --- Приветствие при первом запуске ---
    if not st.session_state.welcome_shown:
        st.info(WELCOME_TEXT)
        st.session_state.welcome_shown = True

    st.title("📚 EnglishCard - Изучай английский с удовольствием!")

    render_sidebar()

    if st.session_state.user_id is None:
        st.markdown(
            "👈 Введите имя в боковой панели и нажмите **Войти**, "
            "чтобы начать тренировку."
        )
        return

    words = get_user_words(st.session_state.user_id)

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📖 Изучение",
        "➕ Добавить слово",
        "🗑️ Удалить слово",
        "📊 Статистика",
        "🗄️ Схема БД",
    ])

    with tab1:
        render_study_tab(words)
    with tab2:
        render_add_word_tab()
    with tab3:
        render_delete_word_tab(words)
    with tab4:
        render_statistics_tab(st.session_state.user_id)
    with tab5:
        render_schema()


if __name__ == "__main__":
    main()
