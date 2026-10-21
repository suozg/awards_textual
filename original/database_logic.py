# database_logic.py
import re
from datetime import datetime, timedelta
from collections import defaultdict
from itertools import chain
import io
import os
from PIL import Image
from sqlcipher3 import dbapi2 as sqlite3 
import wx
from create_db0 import create_database, is_database_existing

"""from config import (DATABASE_FILE_PATH, DEF_FUT_LABEL, MASTERKEY,
                    SHOW_MORE_IMAGES, START_YEAR)"""

RankingValues = ["", "Найвища", "Державні", "Від центральних ов", "Відомчі", "Від місцевих ов", "Від керівництва", "Інші"]


def connect_to_database(passwd, database_file_path):
    """Підключення до бази даних з паролем. Повертає conn і cursor."""
    try:
        conn = sqlite3.connect(database_file_path)
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA key = '{passwd}';")
        # SQLCipher 3 сумісність
        cursor.execute("PRAGMA cipher_compatibility = 3;")  
        cursor.execute("PRAGMA kdf_iter = 64000;")
        
        # --- Оптимізація швидкодії SQLite/SQLCipher ---
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA cache_size = -64000;") # Кеш 64 МБ у пам'яті
        cursor.execute("PRAGMA temp_store = MEMORY;")
        
        # перевірка доступності таблиці
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        if cursor.fetchall():
            conn.create_function("LOWER", 1, sqlite_lower)
            return conn, cursor
    except Exception as e:
        print("Помилка підключення до бази:", e)
        return None, None


def sqlite_lower(value_):
    """Функція для приведення рядка до нижнього регістру для SQL-запитів."""
    return str(value_).lower()


def is_tipa_inn(value):
    """Попередня перевірка РНОКПП."""
    return bool(re.fullmatch(r"\d{10}", value))  # РНОКПП повинен містити 10 цифр


# --- Функція для обробки ІНН ---
def is_valid_INN(inn):
    """ Перевірка РНОКПП та обчислення дати народження """
    if re.fullmatch(r"\d{10}", inn):
        try:
            digits = [int(ch) for ch in inn]

            k1 = (digits[0]*-1) + (digits[1]*5) + (digits[2]*7) + (digits[3]*9) + \
                 (digits[4]*4) + (digits[5]*6) + (digits[6]*10) + (digits[7]*5) + (digits[8]*7)
            k2 = k1 % 11
            k3 = 0 if k2 == 10 else k2

            if digits[9] == k3:
                days_to_add = int(inn[:5])
                start_date = datetime(1899, 12, 31)
                date_and_delta = start_date + timedelta(days=days_to_add)
                birth_date = date_and_delta.strftime("%Y-%m-%d")
                return birth_date
            else:
                return ""
        except Exception as e:
            return ""
            
    return ""

def _get_formatted_inn_display(raw_inn_value):
    """
    Обробляє сире значення ІНН з бази даних, валідує його
    і повертає форматований рядок для відображення.
    """
    inn_str = ''
    if raw_inn_value is not None:
        try:
            inn_str = str(int(float(raw_inn_value)))
        except (ValueError, TypeError):
            inn_str = str(raw_inn_value).strip()

    validation_result = is_valid_INN(inn_str)
    display_inn = inn_str

    if validation_result == "":
        if display_inn:
            display_inn += " (невірний)"
        else:
            display_inn = " (невірний)"

    return display_inn


def execute_query(cursor, query, params=None):
    """Універсальна функція для виконання SQL-запитів."""
    cursor.execute(query, params or {})
    return cursor.fetchall()


# сервісні дані
def get_service_settings_data(cursor):
    if not cursor:
        return None
    try:
        query = "SELECT logo, exel_butt, view_butt, or_butt, zvit_dir, zvit_fields, show_hellou, id, pass, cookies, img_homer, img_homer2, last_time_changes FROM service_ LIMIT 1"
        cursor.execute(query)
        settings_row = cursor.fetchone()
        return settings_row
    except Exception as e:
        return None


# ------------------------ запит пошуку -------------------------------------
def search_q(query, cursor, search_id=None):
    """Функція пошуку по ПІБ або РНОКПП в базі даних."""
    if not cursor:
        return [], "Помилка: недійсний курсор БД", [], 0, {}

    if search_id:
        results = execute_query(cursor, "SELECT * FROM personality WHERE id = :id", {"id": search_id})
    else:
        if not query or len(query) < 3:
            return [], "Занадто короткий запит", [], 0, {}
        if is_tipa_inn(query):
            results = execute_query(cursor, "SELECT * FROM personality WHERE inn = :inn", {"inn": query})
        else:
            results = execute_query(cursor, "SELECT * FROM personality WHERE LOWER(name) LIKE :name", {"name": query.lower() + "%"})

    if results:
        ids = [row[0] for row in results]
        stringTab1, imgList, counts_gid01, source_data_award_and_presentation = get_award_and_presentation_info(ids, cursor)
    else:
        stringTab1 = "Нічого не знайдено"
        imgList = []
        counts_gid01 = 0
        source_data_award_and_presentation = {}

    return results, stringTab1, imgList, counts_gid01, source_data_award_and_presentation


# ------------------------ ОПТИМІЗОВАНІ ЗАПИТИ ВИБІРКИ -------------------------------------

def get_award_and_presentation_info(person_ids, cursor):
    """Оптимізоване отримання інформації про нагороди та подання без запитів у циклі."""
    if not person_ids:
        return "", [], 0, {}

    stringTab1 = ""
    imgList = []
    counts_gid01 = 0
    source_data_award_and_presentation = defaultdict(lambda: {'meed': [], 'presentations': []})

    placeholders = ','.join('?' for _ in person_ids)

    # 1. Один пакетний запит для ВСІХ нагород з JOIN 
    awards_query = f"""
        SELECT 
            m.id_personality, m.id_award, m.date_decree, m.decree, m.number_meed,
            m.date_handover, m.handover, m.consignment_note,
            p.name, p.rank, p.inn, p.unit,
            a.denotation,
            m.id, m.dead,
            hto_p.name AS hto_name
        FROM meed m
        LEFT JOIN personality p ON p.id = m.id_personality
        LEFT JOIN award a ON a.id = m.id_award
        LEFT JOIN personality hto_p ON hto_p.id = RTRIM(m.handover, '$')
        WHERE m.id_personality IN ({placeholders})
    """
    cursor.execute(awards_query, person_ids)
    all_awards = cursor.fetchall()

    # ГРУПУВАННЯ НАГОРОД БАЗИ
    awards_by_person = defaultdict(list)
    for row in all_awards:
        awards_by_person[row[0]].append(row)

    # 2. Один пакетний запит для ВСІХ подань з JOIN
    pres_query = f"""
        SELECT 
            pr.registration, pr.date_registration,
            p.name, p.rank, p.inn, p.unit,
            pr.id, pr.id_meed, pr.worker, pr.report, pr.text_presentation,
            pr.id_personality
        FROM presentation pr
        LEFT JOIN personality p ON p.id = pr.id_personality
        WHERE pr.id_personality IN ({placeholders})
    """
    cursor.execute(pres_query, person_ids)
    all_presentations = cursor.fetchall()

    # ГРУПУВАННЯ ПОДАНЬ БАЗИ
    pres_by_person = defaultdict(list)
    for row in all_presentations:
        pres_by_person[row[11]].append(row)

    # 3. Швидке формування результатів у пам'яті
    for pid in person_ids:
        person_output = ""
        awards = awards_by_person.get(pid, [])
        presentations = pres_by_person.get(pid, [])

        processed_awards_data = []

        if awards:
            counts_gid01 += 1            

        for row in awards:
            display_inn = _get_formatted_inn_display(row[10]) # inn залишився під індексом 10

            deadTxt = " (посмертно)" if str(row[14]) == "1" else "" # m.dead перемістився з row[16] на row[14]
            if person_output == "": 
                person_output += f'\n* {row[8]} {row[9]} ({display_inn}, {row[11]}) * \n\n нагороди ({len(awards)})'
            person_output += f'\n {row[12]}\n - указ/наказ : №{row[3]} від {row[2]} {deadTxt};\n' # a.denotation перемістився з row[14] на row[12]

            imgList.append(row[1])

            string_handover_value = ""
            if row[6] or row[7]:
                person_output += f' - накладна {row[7]}.'
                string_handover_value = f'\n - нагороду {row[4]}'
                htoid = str(row[6]) if row[6] is not None else ""
                
                if htoid:
                    protokol = ", є протокол вручення" if htoid.endswith("$") else ""
                    hto_name = row[15] if row[15] else htoid.rstrip("$") # hto_name перемістився з row[17] на row[15]
                    string_handover_value += f' вручено: {row[5]}, {hto_name}{protokol}.\n'
                else:
                    string_handover_value += ' не вручено.\n'

                person_output += f' {string_handover_value}'

            award_details = {
                'raw_data': row,
                'handover_info': string_handover_value
            }
            processed_awards_data.append(award_details)

        source_data_award_and_presentation[pid]['meed'] = processed_awards_data

        if person_output.strip() and presentations:
            person_output += f'\n подання ({len(presentations)})\n'

        source_data_award_and_presentation[pid]['presentations'] = presentations

        for row in presentations:
            display_inn = _get_formatted_inn_display(row[4]) 

            worker = "ВП" if row[8] == 0 else "МПЗ" if row[8] == 1 else "інші"

            if row[7] is None:
                Vidmova = "(НА РОЗГЛЯДІ)"
            elif str(row[7]) == "0":
                Vidmova = "(ВІДМОВЛЕНО)"
            else:
                Vidmova = ""

            deadTxtP = "(посмертно)" if row[9] == "посмертно" else ""
            t_report = "" if row[9] == "посмертно" else row[9]

            if person_output == "":
                person_output += f'\n* {row[3]} {row[2]} ({display_inn}, {row[5]}) *\n\n подання ({len(presentations)})\n'
            person_output += f' №{row[0]} від {row[1]} {deadTxtP} вик.{worker} {t_report} {Vidmova}\n'

        if person_output.strip():
            stringTab1 += person_output + "\n****\n"

    return stringTab1, imgList, counts_gid01, dict(source_data_award_and_presentation)


def get_award_image_blobs_for_search(imgList, counts_gid01, cursor):
    """ Видобуває бінарні дані зображень (BLOB) для списку ID нагород. """
    if not cursor or not imgList or counts_gid01 != 1:
        return []

    requested_ids = [int(item) for item in imgList if isinstance(item, (int, str)) and str(item).isdigit()]
    
    if not requested_ids:
        return []

    try:
        unique_ids_for_query = list(set(requested_ids))
        placeholders = ','.join('?' for _ in unique_ids_for_query)
        query = f"SELECT id, img, ranking FROM award WHERE id IN ({placeholders})"
        cursor.execute(query, unique_ids_for_query)
        id_to_blob = {row[0]: row[1] for row in cursor.fetchall()}
        final_blobs = []
        for req_id in requested_ids:
            blob = id_to_blob.get(req_id)
            if blob is not None and isinstance(blob, bytes):
                final_blobs.append(blob)
        return final_blobs
    except Exception:
        return []


# -------------- клас для побудови графіка ------------------------

class AwardDataLoader:
    def __init__(self, start_year):
        self.start_year = start_year
        self.last_meed_date = None
        self.count_present = None
        self.count_presentPers = None
        self.x_data = []
        self.y_data_state_awards = []
        self.y_data_all_awards = []
        self.y_data_presentations = []
        self.state_award_ids = set()

    def load_data(self, cursor):
        if not cursor:
            self._initialize_empty_data()
            return

        try:
            query = """
                SELECT
                    (SELECT date_decree FROM meed ORDER BY date_decree DESC LIMIT 1),
                    (SELECT COUNT(id) FROM presentation WHERE id_meed IS NULL OR TRIM(id_meed) = ''),
                    (SELECT COUNT(id) FROM presentation WHERE (id_meed IS NULL OR TRIM(id_meed) = '') AND worker = 0)
            """
            main_data_row = execute_query(cursor, query)
            if main_data_row and main_data_row[0] and len(main_data_row[0]) == 3:
                self.last_meed_date, self.count_present, self.count_presentPers = main_data_row[0]
            else:
                self._initialize_empty_data()
                return

            query = "SELECT id FROM award WHERE ranking <= 5"
            state_award_results = execute_query(cursor, query)
            self.state_award_ids = {row[0] for row in state_award_results}

            query = "SELECT date_decree, id_award FROM meed"
            all_meeds = execute_query(cursor, query)

            query = "SELECT date_registration FROM presentation"
            all_presentations = execute_query(cursor, query)

            state_awards_by_year = defaultdict(int)
            all_awards_by_year = defaultdict(int)
            presentations_by_year = defaultdict(int)

            for date_str, award_id in all_meeds:
                try:
                    year = int(date_str[:4])
                    all_awards_by_year[year] += 1
                    if award_id in self.state_award_ids:
                        state_awards_by_year[year] += 1
                except (ValueError, TypeError):
                    continue

            for (date_str,) in all_presentations:
                try:
                    year = int(date_str[:4])
                    presentations_by_year[year] += 1
                except (ValueError, TypeError):
                    continue

            self.x_data = []
            self.y_data_state_awards = []
            self.y_data_all_awards = []
            self.y_data_presentations = []
            current_year = datetime.now().year

            for year in range(self.start_year, current_year + 1):
                self.x_data.append(year)
                self.y_data_state_awards.append(state_awards_by_year.get(year, 0))
                self.y_data_all_awards.append(all_awards_by_year.get(year, 0))
                self.y_data_presentations.append(presentations_by_year.get(year, 0))

        except Exception:
            self._initialize_empty_data()

    def _initialize_empty_data(self):
        self.x_data = []
        self.y_data_state_awards = []
        self.y_data_all_awards = []
        self.y_data_presentations = []
        self.last_meed_date = "Помилка завантаження даних"
        self.count_present = 0
        self.count_presentPers = 0
        self.state_award_ids = set()

    def get_graph_data(self):
        return self.x_data, self.y_data_state_awards, self.y_data_all_awards, self.y_data_presentations

    def get_status_text(self):
        date_str = str(self.last_meed_date) if self.last_meed_date else "Немає даних"
        return f"Остання нагорода: {date_str}, нерозглянуті подання: {self.count_present} (ВП - {self.count_presentPers})"


def get_units_and_ranks(cursor):
    loaded_units = ['']
    loaded_ranks = []

    try:
        query = "SELECT rank_src, unit_src FROM libs"
        raw_data = execute_query(cursor, query)

        unique_units_set = set()
        unique_ranks_set = set()

        for row in raw_data:
            if row and row[0] is not None and str(row[0]).strip():
                unique_ranks_set.add(str(row[0]).strip())
            if row and row[1] is not None and str(row[1]).strip():
                unique_units_set.add(str(row[1]).strip())

        loaded_ranks = sorted(list(unique_ranks_set))
        loaded_units.extend(sorted(list(unique_units_set)))

        return (loaded_ranks, loaded_units)

    except Exception as e:
        raise RuntimeError(f"Помилка бази даних при завантаженні підрозділів та рангів: {e}")


def get_treedata(cursor):
    if not cursor:
        return {}

    awards_data = {}
    try:
        cursor.execute("SELECT id, denotation, law, grounds, img, ranking FROM award ORDER BY ranking;")
        rows = cursor.fetchall()
        for row in rows:
            award_id, award_name, law_desc, grounds_desc, image_data, ranking = row
            ranking_description = "Невідоме ранжирування"

            if isinstance(ranking, int):
                if 0 <= ranking < len(RankingValues):
                    ranking_description = RankingValues[ranking]

            if ranking_description not in awards_data:
                awards_data[ranking_description] = {}

            awards_data[ranking_description][award_name] = {
                "award_id": award_id,
                "law": law_desc,
                "grounds": grounds_desc,
                "image": image_data,
                "original_ranking_int": ranking,
            }

    except sqlite3.Error:
        awards_data = {}

    return awards_data


def save_award_to_db(conn, cursor, award_id, award_name, short_desc, full_desc, image_data, ranking):
    try:
        if not conn or not cursor:
            return False

        cleaned_award_name = award_name.strip().replace('\n', ' ')

        query = """
            UPDATE award SET
                denotation = ?,
                law = ?,
                grounds = ?,
                img = ?,
                ranking = ?
            WHERE id = ?
        """
        params = (cleaned_award_name, short_desc, full_desc, image_data, ranking, award_id)

        cursor.execute(query, params)
        conn.commit()

        return cursor.rowcount > 0

    except sqlite3.Error:
        if conn:
            conn.rollback()
        return False
    except Exception:
        return False


def create_award_in_db(conn, cursor, category_name, award_name, short_desc, full_desc, image_data, ranking):
    try:
        cleaned_award_name = award_name.strip().replace('\n', ' ')

        cursor.execute("""
            INSERT INTO award (denotation, law, grounds, img, ranking)
            VALUES (?, ?, ?, ?, ?)
        """, (cleaned_award_name, short_desc, full_desc, image_data, ranking))
        conn.commit()
        return cursor.lastrowid
    except sqlite3.Error:
        conn.rollback()
        return None


def delete_award_from_db(conn, cursor, award_id):
    try:
        cursor.execute("DELETE FROM award WHERE id = ?", (award_id,))
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.Error:
        conn.rollback()
        return False


def get_formatted_unique_awarded_distinctions(cursor, rank_filter=None):
    formatted_list = []
    unique_formatted_list = []

    rank_number_filter = None
    if rank_filter and rank_filter.strip():
        try:
            rank_number_filter = RankingValues.index(rank_filter)
        except ValueError:
            raise RuntimeError(f"Попередження: Ранг '{rank_filter}' не знайдено у списку рангів.")

    try:
        query = """
            SELECT DISTINCT a.denotation
            FROM meed m
            JOIN award a ON m.id_award = a.id
            WHERE m.date_decree IS NOT NULL
        """
        params = ()

        if rank_number_filter is not None:
            query += " AND a.ranking = ?"
            params = (rank_number_filter,)

        query += " ORDER BY a.ranking, a.denotation"

        raw_data = execute_query(cursor, query, params)

        for row in raw_data:
            if row and row[0]:
                unique_formatted_list.append(row[0])

        return unique_formatted_list

    except Exception as e:
        raise RuntimeError(f"Помилка бази даних при завантаженні та формуванні списку нагород: {e}")


def search_presentations(cursor, query):
    if not query:
        return "EMPTY", [], "Введіть пошуковий запит."

    cursor.execute("""
        SELECT * FROM presentation_fts WHERE text_presentation MATCH ?
    """, (query,))

    results = cursor.fetchall()
    return "OK", results, f"Знайдено текстів: {len(results)}"

def get_presentation_info(cursor, pres_id):
    cursor.execute("""
        SELECT registration, date_registration, id_meed
        FROM presentation WHERE id=?
    """, (pres_id,))

    result = cursor.fetchone()
    return result



