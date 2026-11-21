"""Bu ilana başvurabilir miyim? Kurallar profile.py'de."""
from __future__ import annotations

import re

from . import profile
from .models import Ilan
from .text import fold

OK, CHECK, SKIP = "ok", "check", "skip"

_B = r"(?<![a-z])"  # kelime başı: "lisans" "onlisans" içinde eşleşmesin
_BOLUM_OK = [re.compile(_B + p) for p in profile.BOLUM_OK]
_MAYBE = [(re.compile(_B + p), why) for p, why in profile.BOLUM_MAYBE]
# "Bölümler ekte/tabloda/kılavuzda" türü sebepler
_REFER = {why for _, why in profile.BOLUM_MAYBE if "tablo" in why or "ekinde" in why or "kılavuz" in why}
_CAUTION = [(re.compile(_B + p), why) for p, why in profile.CAUTION]
_BILISIM = [re.compile(_B + p) for p in profile.BILISIM_PERSONELI]


def _snippet(text: str, m: re.Match) -> str:
    return text[max(0, m.start() - 40): m.end() + 40].strip()


def _additional_conditions(text: str) -> tuple[str, str] | None:
    """Compare only explicit age, body-measurement and KPSS conditions."""
    failures, uncertain, passed = [], [], []

    age_max = re.compile(
        r"(\d{1,2})\s*yas(?:ini)?\s*(?:doldurmamis|gecmemis|asmamis)"
        r"|(\d{1,2})\s*yasindan\s*gun\s*almamis"
        r"|en\s*fazla\s*(\d{1,2})\s*yas"
    )
    age_min = re.compile(r"(\d{1,2})\s*yasini\s*tamamlamis|en\s*az\s*(\d{1,2})\s*yas")
    age_hits = False
    for match in age_max.finditer(text):
        age_hits = True
        limit = int(next(x for x in match.groups() if x))
        if profile.YAS < limit - 1:
            passed.append("yaş koşulu uygun görünüyor")
        elif profile.YAS == limit - 1:
            uncertain.append("yaş koşulunun ilan tarihindeki hesabını kontrol edin")
        else:
            failures.append("yaş sınırı karşılanmıyor")
    for match in age_min.finditer(text):
        age_hits = True
        limit = int(next(x for x in match.groups() if x))
        if profile.YAS >= limit:
            passed.append("yaş koşulu uygun görünüyor")
        elif profile.YAS == limit - 1:
            uncertain.append("yaş koşulunun ilan tarihindeki hesabını kontrol edin")
        else:
            failures.append("yaş sınırı karşılanmıyor")
    if "yas" in text and not age_hits:
        uncertain.append("yaş şartını ilandaki tarih ve ifadeye göre kontrol edin")

    height_rule = re.compile(
        r"(?:\bboy(?:u|unda|lu)?\b[^\n]{0,30}(?:en\s*az|asgari|minimum)[^\d]{0,8}(\d{1,3}(?:[.,]\d{1,2})?)"
        r"|(?:en\s*az|asgari|minimum)[^\d]{0,8}(\d{1,3}(?:[.,]\d{1,2})?)[^\n]{0,20}\bboy(?:u|unda|lu)?\b)"
    )
    height_hits = list(height_rule.finditer(text))
    if re.search(r"\bboy(?:u|unda|lu)?\b|boy-kilo|boy kilo", text):
        if height_hits and any(
            re.search(r"erkek|kadin", text[max(0, m.start() - 40):m.end() + 40])
            for m in height_hits
        ):
            uncertain.append("boy şartı cinsiyete göre verilmiş; ilgili koşulu kontrol edin")
        elif height_hits:
            for match in height_hits:
                raw = next(x for x in match.groups() if x).replace(",", ".")
                value = float(raw)
                required_cm = round(value * 100) if value < 3 else round(value)
                (passed if profile.BOY_CM >= required_cm else failures).append(
                    "boy koşulu uygun görünüyor" if profile.BOY_CM >= required_cm else "boy sınırı karşılanmıyor"
                )
        elif "boy-kilo" in text or "boy kilo" in text:
            uncertain.append("boy-kilo tablosundaki koşulu kontrol edin")
        else:
            uncertain.append("boy şartı metinden net çıkarılamadı")

    bmi = profile.KILO_KG / ((profile.BOY_CM / 100) ** 2)
    bmi_context = re.search(r"(?:beden kitle indeksi|vucut kitle indeksi|\bbmi\b)", text)
    if bmi_context:
        nearby = text[max(0, bmi_context.start() - 50): bmi_context.end() + 100]
        bmi_max = re.search(r"(?:en fazla|azami|maksimum|ust sinir)\s*(\d{1,2}(?:[.,]\d)?)", nearby)
        bmi_min = re.search(r"(?:en az|asgari|minimum|alt sinir)\s*(\d{1,2}(?:[.,]\d)?)", nearby)
        bmi_range = re.search(r"(\d{1,2}(?:[.,]\d)?)\s*(?:ile|-|–)\s*(\d{1,2}(?:[.,]\d)?)", nearby)
        if bmi_range and not (bmi_max or bmi_min):
            bmi_min, bmi_max = bmi_range, bmi_range
            min_value, max_value = (float(x.replace(",", ".")) for x in bmi_range.groups())
            min_ok, max_ok = bmi >= min_value, bmi <= max_value
        elif bmi_max or bmi_min:
            max_ok = not bmi_max or bmi <= float(bmi_max.group(1).replace(",", "."))
            min_ok = not bmi_min or bmi >= float(bmi_min.group(1).replace(",", "."))
        else:
            max_ok = min_ok = False
        if bmi_max or bmi_min or bmi_range:
            (passed if max_ok and min_ok else failures).append(
                "beden kitle indeksi koşulu uygun görünüyor" if max_ok and min_ok else "beden kitle indeksi sınırı karşılanmıyor"
            )
        else:
            uncertain.append("beden kitle indeksi koşulunu ilandan kontrol edin")

    weight_max = re.search(
        r"(?:kilo|agirlik)[^\d\n]{0,35}(?:en fazla|azami|maksimum)[^\d]{0,8}(\d{2,3})"
        r"|(?:en fazla|azami|maksimum)[^\d]{0,8}(\d{2,3})\s*(?:kg|kilogram)", text
    )
    weight_min = re.search(
        r"(?:kilo|agirlik)[^\d\n]{0,35}(?:en az|asgari|minimum)[^\d]{0,8}(\d{2,3})"
        r"|(?:en az|asgari|minimum)[^\d]{0,8}(\d{2,3})\s*(?:kg|kilogram)", text
    )
    if weight_max or weight_min:
        max_match = weight_max.group(1) or weight_max.group(2) if weight_max else None
        min_match = weight_min.group(1) or weight_min.group(2) if weight_min else None
        max_ok = not max_match or profile.KILO_KG <= int(max_match)
        min_ok = not min_match or profile.KILO_KG >= int(min_match)
        (passed if max_ok and min_ok else failures).append(
            "kilo koşulu uygun görünüyor" if max_ok and min_ok else "kilo sınırı karşılanmıyor"
        )
    elif re.search(r"\b(?:kilo|agirlik)\b|\bkg\b|boy-kilo|boy kilo", text) and not bmi_context:
        uncertain.append("kilo veya boy-kilo koşulunu ilandan kontrol edin")

    if "kpss" in text:
        score_type = re.search(r"kpss\s*p?\s*(3|93|94)\b|p\s*(3|93|94)\s*puan", text)
        if not score_type:
            uncertain.append("KPSS puan türü ve sıralama koşulunu kontrol edin")
        else:
            code = next(x for x in score_type.groups() if x)
            score = profile.KPSS_LISANS_PUANI if code == "3" else (
                profile.KPSS_ONLISANS_PUANI if code == "93" else None
            )
            if score is None:
                uncertain.append("bu KPSS puan türü profilinizde kayıtlı değil")
            else:
                context = text[max(0, score_type.start() - 100):score_type.end() + 140]
                minimum = re.search(
                    r"(?:en\s*az|asgari|minimum|min\.?|taban\s*puan(?:i)?)\s*(\d{2,3})\s*(?:puan)?"
                    r"|\b(\d{2,3})\s*puan\s*(?:ve\s*uzeri|almak|olmak)", context
                )
                if not minimum:
                    uncertain.append("KPSS puan sıralamasını ve taban puanı ilandan kontrol edin")
                else:
                    required = int(next(x for x in minimum.groups() if x))
                    exam_years = [int(y) for y in re.findall(r"20\d{2}", context)]
                    if exam_years and profile.KPSS_LISANS_YILI is None:
                        uncertain.append("kabul edilen KPSS sınav yılı profilinizde kayıtlı değil")
                    elif exam_years and profile.KPSS_LISANS_YILI not in exam_years:
                        failures.append("KPSS sınav yılı kabul edilen dönemle eşleşmiyor")
                    elif score >= required:
                        passed.append("KPSS taban puanı karşılanıyor; sıralama sonucu ayrıca belirlenir")
                    else:
                        failures.append("KPSS taban puanı karşılanmıyor")

    if failures:
        return CHECK, "olası uyumsuzluk; başvurmadan önce ilanı kontrol edin: " + "; ".join(dict.fromkeys(failures))
    if uncertain:
        return CHECK, "; ".join(dict.fromkeys(uncertain))
    if passed:
        return OK, "; ".join(dict.fromkeys(passed))
    return None


def decide(i: Ilan) -> tuple[str, str]:
    """(OK | CHECK | SKIP, sebep)."""
    head = fold(f"{i.title} {i.category}")
    for kw, why in profile.SKIP_TITLE:
        if re.search(_B + re.escape(kw), head):
            return SKIP, why
    cat = fold(i.category)
    if any(c in cat for c in profile.SKIP_CATEGORY):
        return SKIP, f"ilan türü: {i.category}"

    if i.source == "iskur" and i.id.isdigit() and not re.search(profile.ISKUR_MESLEK_OK, head):
        return SKIP, "meslek alanınızla ilgili değil"

    text = fold(i.detail)
    if (re.search(r"2547 ?s ?ayili", text[:1500]) or "akademik birim" in text[:1500]) \
            and any(a in text[:3000] for a in profile.ACADEMIC_BODY + ["akademik birim"]):
        return SKIP, "akademik kadro (2547 sayılı Kanun)"
    if profile.DENEYIM_YIL < 3 and any(p.search(f"{head} {text}") for p in _BILISIM):
        return SKIP, "sözleşmeli bilişim personeli: tüm kadrolar en az 3 yıl deneyim istiyor"

    if i.has_text:
        m = next((m for p in _BOLUM_OK if (m := p.search(text))), None)
        if not m:
            maybe = next((why for p, why in _MAYBE if p.search(text)), None)
            if maybe in _REFER and re.search(profile.NAMED_LIST, text):
                maybe = None  # bölüm listesi metinde var ve profildeki bölümler içinde değil
            if maybe:
                return CHECK, f"{maybe}; bölüm şartını kontrol edin"
            return SKIP, f"bölüm şartı {profile.BOLUM} içermiyor"
        why = f"bölüm şartı uygun: “…{_snippet(text, m)}…”"
        cautions = [w for p, w in _CAUTION if p.search(text)]
        extra = _additional_conditions(text)
        if extra and extra[0] == SKIP:
            return SKIP, extra[1]
        if extra:
            why += f"; {extra[1]}"
            if extra[0] == CHECK:
                return CHECK, why
        if cautions:
            return CHECK, f"{why}; ama {', '.join(cautions)}"
        return OK, why

    other = re.search(r"([a-z]+) muhendisligi", head)
    if other and other.group(1) not in ("bilgisayar", "yazilim"):
        return SKIP, f"başlıkta farklı bölüm: {other.group(0)}"
    for kw, why in profile.SKIP_TITLE_NO_TEXT:
        if re.search(_B + re.escape(kw), head):
            return SKIP, why
    if any(k in head for k in profile.TITLE_OK):
        return CHECK, "başlık uygun görünüyor; ilan metni ve kişisel koşullar doğrulanamadı"
    return CHECK, "ilan metni okunamadı, şartları kontrol edin"
