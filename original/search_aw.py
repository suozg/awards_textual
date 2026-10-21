#!/usr/bin/env python3

import re
import time
from datetime import datetime
import requests
import pandas as pd
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE = "https://zakon.rada.gov.ua"
YEARS = range(2014, 2027)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) "
                  "AppleWebKit/537.36 Chrome/120 Safari/537.36"
}

KEYWORDS = (
    "державними нагородами",
    "державних нагород",
    "герой україни",
    "золота зірка",
    "нагородження",
    "нагородити",
    "присвоєння звання",
)

session = requests.Session()
session.headers.update(HEADERS)


def get(url, params=None):
    try:
        r = session.get(url, params=params, timeout=30)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        return r.text
    except Exception as e:
        print("ERROR:", url, e)
        return None


def normalize(text):
    text = text.upper().replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def get_year_documents(year):
    """
    Отримує всі укази за рік. Для поточного року або якщо немає архіву — 
    використовує пошукову форму сайту ВРУ.
    """
    current_year = datetime.now().year
    documents = {}
    pattern = re.compile(r"/laws/show/\d+/" + str(year))

    html = None
    if year < current_year:
        first_url = f"{BASE}/laws/main/t3y{year}"
        html = get(first_url)

    if html:
        print(f"Знайдено архівну сторінку для {year} року.")
        soup = BeautifulSoup(html, "html.parser")

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if pattern.search(href):
                url = urljoin(BASE, href)
                title = normalize(a.get_text(" ", strip=True))
                documents[url] = title

        pages = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "page=" in href:
                pages.add(urljoin(BASE, href))

        for page_url in sorted(pages):
            p_html = get(page_url)
            if not p_html:
                continue
            soup = BeautifulSoup(p_html, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if pattern.search(href):
                    url = urljoin(BASE, href)
                    title = normalize(a.get_text(" ", strip=True))
                    documents[url] = title
            time.sleep(0.15)

        return list(documents.items())

    print(f"Використовуємо пошук на сайті для {year} року...")
    search_queries = [
        "Про відзначення державними нагородами України",
        "Про присвоєння звання Герой України",
        "нагородити"
    ]
    
    url = f"{BASE}/laws/main"
    for query in search_queries:
        params = {
            "find": "2", "dat": "00000000", "user": "a",
            "text": query, "textl": "2", "bool": "and",
            "org": "4", "typ": "3", "yer": "0000", "mon": "00", "day": "00",
            "dat_from": f"{year}-01-01",
            "dat_to": f"{int(year) + 1}-01-01",
            "datl": "3", "numl": "2", "num": "", "minjustl": "2", "minjust": ""
        }

        try:
            r_text = get(url, params=params)
            if not r_text:
                continue
            
            soup = BeautifulSoup(r_text, "html.parser")
            doc_links = soup.find_all("div", class_="doc")

            for doc in doc_links:
                a_tag = doc.find("a")
                if not a_tag or not a_tag.has_attr("href"):
                    continue
                
                href = a_tag["href"]
                if pattern.search(href):
                    full_url = urljoin(BASE, href)
                    title = normalize(a_tag.get_text(" ", strip=True))
                    documents[full_url] = title

            time.sleep(0.2)
        except Exception as e:
            print(f"Помилка пошуку для запиту '{query}': {e}")

    return list(documents.items())


def is_award_document(title):
    title = normalize(title)
    return any(k.upper() in title for k in KEYWORDS)


def parse_decree(url, list_title, year):
    html = get(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    full_text = soup.get_text("\n", strip=True)

    if "ПОСМЕРТНО" not in normalize(full_text):
        return []

    # Витягуємо правильний номер указу з URL (наприклад, /laws/show/891/2022)
    match_ukaz = re.search(r'/laws/show/(\d+/\d+|\d+)', url)
    ukaz_num = match_ukaz.group(1) if match_ukaz else url.split("/")[-2]

    rows = []
    current_award = ""

    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue

        parts = [c.get_text(" ", strip=True) for c in cells]
        text = " ".join(parts)
        norm = normalize(text)

        if not text:
            continue

        if any(x in norm for x in (
            "ОРДЕНОМ", "ОРДЕНАМИ", "МЕДАЛЛЮ", "МЕДАЛЯМИ",
            "ВІДЗНАКОЮ", "ЗВАННЯ ГЕРОЙ УКРАЇНИ", "ЗОЛОТА ЗІРКА", "ПОЧЕСНОЮ ГРАМОТОЮ",
        )):
            current_award = text

        if "ПОСМЕРТНО" in norm:
            clean = re.sub(r"\s*\(посмертно\)", "", text, flags=re.I)
            
            m = re.search(
                r"\b([А-ЯІЇЄҐЁA-Z][А-ЯІЇЄҐЁA-Z'’\-]+)"
                r"\s+([А-ЯІЇЄҐЁA-Z][а-яіїєґёa-z'’\-]+)"
                r"\s+([А-ЯІЇЄҐЁA-Z][а-яіїєґёa-z'’\-]+)",
                clean,
                re.UNICODE
            )

            if m:
                pib = " ".join(m.groups())
            else:
                pib = clean.strip()

            rows.append({
                "Рік": year,
                "Указ": ukaz_num,
                "ПІБ": pib,
                "Нагорода": current_award,
                "Рядок": text,
                "Назва указу": list_title,
                "Посилання": url,
            })

    if not rows:
        for line in full_text.splitlines():
            if "ПОСМЕРТНО" not in normalize(line):
                continue

            clean = re.sub(r"\s*\(посмертно\)", "", line, flags=re.I)
            rows.append({
                "Рік": year,
                "Указ": ukaz_num,
                "ПІБ": clean.strip(),
                "Нагорода": current_award,
                "Рядок": line.strip(),
                "Назва указу": list_title,
                "Посилання": url,
            })

    return rows


def main():
    all_rows = []

    for year in YEARS:
        print()
        print("=" * 60)
        print("РІК:", year)
        print("=" * 60)

        docs = get_year_documents(year)
        print("Знайдено указів:", len(docs))

        if year >= 2026:
            award_docs = docs
        else:
            award_docs = [
                (url, title)
                for url, title in docs
                if is_award_document(title)
            ]
        
        print("Можливих нагородних указів:", len(award_docs))

        for n, (url, title) in enumerate(award_docs, 1):
            print(f"[{n}/{len(award_docs)}] {url.split('/')[-2]}/{year}")
            rows = parse_decree(url, title, year)

            if rows:
                print(f"   -> посмертних записів: {len(rows)}")
                all_rows.extend(rows)

            time.sleep(0.2)

    if not all_rows:
        print("\nНічого не знайдено.")
        return

    df = pd.DataFrame(all_rows)

    df["ПІБ_normal"] = df["ПІБ"].astype(str).map(normalize)
    df = df.drop_duplicates(subset=["Рік", "Указ", "ПІБ_normal"])

    unique = (
        df.sort_values(["ПІБ_normal", "Рік"])
        .drop_duplicates("ПІБ_normal", keep="first")
        .copy()
    )

    counts = df.groupby("ПІБ_normal").size().reset_index(name="Кількість записів")
    duplicates = counts[counts["Кількість записів"] > 1]

    stats_year = (
        df.groupby("Рік")
        .agg(
            Посмертних_записів=("ПІБ_normal", "size"),
            Унікальних_осіб=("ПІБ_normal", "nunique")
        )
        .reset_index()
    )

    stats_decrees = (
        df.groupby(["Рік", "Указ", "Посилання", "Назва указу"])
        .agg(Посмертних=("ПІБ_normal", "size"))
        .reset_index()
    )

    # Збереження файлів
    df.to_csv("posmertni_nagorody.csv", index=False, encoding="utf-8-sig")
    unique.to_csv("posmertni_unikalni.csv", index=False, encoding="utf-8-sig")
    duplicates.to_csv("posmertni_dubli.csv", index=False, encoding="utf-8-sig")

    with pd.ExcelWriter("posmertni_nagorody.xlsx", engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Всі записи", index=False)
        unique.to_excel(writer, sheet_name="Унікальні особи", index=False)
        stats_year.to_excel(writer, sheet_name="По роках", index=False)
        stats_decrees.to_excel(writer, sheet_name="По указах", index=False)
        duplicates.to_excel(writer, sheet_name="Повторні", index=False)

    # Генерація Markdown-звіту з посиланнями
    md_lines = []
    md_lines.append("# Звіт про збір посмертних нагород\n")
    md_lines.append(f"**Загальна кількість записів:** {len(df)}")
    md_lines.append(f"**Унікальних осіб:** {df['ПІБ_normal'].nunique()}\n")
    
    md_lines.append("## Статистика по роках\n")
    md_lines.append("| Рік | Посмертних записів | Унікальних осіб |")
    md_lines.append("|---|---|---|")
    for _, row in stats_year.iterrows():
        md_lines.append(f"| {row['Рік']} | {row['Посмертних_записів']} | {row['Унікальних_осіб']} |")
    md_lines.append("")

    md_lines.append("## Знайдені укази та посилання\n")
    for _, row in stats_decrees.iterrows():
        ukaz_name = row['Назва указу'] if row['Назва указу'] else f"Указ № {row['Указ']}"
        md_lines.append(f"- **Рік: {row['Рік']}** | [{ukaz_name}]({row['Посилання']}) — посмертних записів: {row['Посмертних']}")

    with open("posmertni_report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    print()
    print("=" * 60)
    print("РЕЗУЛЬТАТ")
    print("=" * 60)
    print("Всього записів:", len(df))
    print("Унікальних осіб:", df["ПІБ_normal"].nunique())
    print()
    print(stats_year.to_string(index=False))
    print()
    print("Файли створено успішно!")


if __name__ == "__main__":
    main()
