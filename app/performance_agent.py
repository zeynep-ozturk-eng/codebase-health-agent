"""Performance Agent — parser.py'den gelen FileFacts.functions ve calls
verisindeki performans sorunu supheli fonksiyonlari LLM ile degerlendirip
yapilandirilmis bulgular uretir.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import dataclass

from google import genai

from app.parser import CallSite, FileFacts, Symbol

SYSTEM_PROMPT = """Sen bir performans statik analiz uzmanisin. Sana bir
dosyadaki supheli fonksiyonlarin kaynak kodu ve o fonksiyon icinde tekrar
eden cagrilar verilecek. Her fonksiyon icin gercekten bir performans sorunu
olup olmadigini degerlendir (yanlis pozitifleri ele).

Degerlendirebilecegin kategoriler:
- nested_loops: ic ice gecmis dongulerden kaynaklanan yuksek zaman karmasikligi (O(n^2) veya daha kotu)
- repeated_expensive_call: bir donguyu veya fonksiyonu her calistirdiginda ayni pahali islemi (db sorgusu, dosya/ag istegi) tekrar tekrar yapmasi (N+1 paterni)
- unnecessary_recomputation: ayni sonucu veren bir hesaplamanin donguyu her seferinde tekrarlanmasi, dongu disina alinip bir kere hesaplanabilecek olmasi
- inefficient_data_structure: yanlis veri yapisi kullanimi (orn. listede tekrar tekrar arama yaparken set/dict kullanilabilecek olmasi)

SADECE asagidaki JSON formatinda cevap ver, baska hicbir metin ekleme:

{
  "findings": [
    {
      "function_name": "get_all_orders",
      "line": 42,
      "category": "repeated_expensive_call",
      "severity": "high",
      "is_real_issue": true,
      "explanation": "Donguye her girildiginde ayri bir veritabani sorgusu (query) calistiriliyor, N+1 sorgu problemi olusuyor.",
      "suggestion": "Tum kayitlari tek bir toplu sorguyla (bulk query / join) baştan cek."
    }
  ]
}

severity: "low" | "medium" | "high"
Eger cagrilar tekrar ediyor gibi gorunse bile gercekten sorunsuzsa (orn.
farkli parametrelerle kasitli olarak cagriliyorsa ve performans etkisi
onemsizse), is_real_issue: false yap ve kisaca neden sorun olmadigini acikla.
"""

# Esikler
MAX_COMPLEXITY_FOR_PERF = 8
MIN_REPEATED_CALL_COUNT = 2

# DB/IO/ag gibi "pahali" sayilabilecek cagri isimleri
EXPENSIVE_CALL_NAMES = frozenset(
    {
        "query", "execute", "fetch", "find", "get", "filter", "all",
        "select", "insert", "update", "delete", "save", "commit",
        "request", "open", "read", "write", "sort", "sorted", "get_or_create",
    }
)


@dataclass(frozen=True, slots=True)
class PerformanceFinding:
    function_name: str
    line: int
    category: str
    severity: str
    is_real_issue: bool
    explanation: str
    suggestion: str


def _calls_within(fn: Symbol, calls: list[CallSite]) -> list[CallSite]:
    """Bir fonksiyonun govdesi icinde kalan cagrilari satir araligina gore filtreler."""
    return [
        c for c in calls
        if fn.span.start_line <= c.span.start_line <= fn.span.end_line
    ]


def _repeated_expensive_calls(fn_calls: list[CallSite]) -> Counter[str]:
    names = [c.name.rsplit(".", 1)[-1] for c in fn_calls if c.name.rsplit(".", 1)[-1] in EXPENSIVE_CALL_NAMES]
    counts = Counter(names)
    return Counter({name: n for name, n in counts.items() if n >= MIN_REPEATED_CALL_COUNT})


def _is_suspicious(fn: Symbol, fn_calls: list[CallSite]) -> bool:
    return (
        fn.complexity > MAX_COMPLEXITY_FOR_PERF
        or bool(_repeated_expensive_calls(fn_calls))
    )


def _reasons(fn: Symbol, repeated: Counter[str]) -> list[str]:
    reasons = []
    if fn.complexity > MAX_COMPLEXITY_FOR_PERF:
        reasons.append(f"karmasiklik {fn.complexity} (esik: {MAX_COMPLEXITY_FOR_PERF}, olasi ic ice donguler)")
    for name, count in repeated.items():
        reasons.append(f"'{name}' cagrisi {count} kez tekrarlaniyor")
    return reasons


def _build_context(source: str, facts: FileFacts, suspicious: list[Symbol]) -> str:
    """Sadece supheli fonksiyonlarin kaynak kodunu cikarir (tum dosyayi degil)."""
    lines = source.splitlines()
    blocks = []

    for fn in suspicious:
        fn_calls = _calls_within(fn, facts.calls)
        repeated = _repeated_expensive_calls(fn_calls)
        start = max(0, fn.span.start_line - 1)
        end = min(len(lines), fn.span.end_line)
        snippet = "\n".join(f"{i + 1}: {lines[i]}" for i in range(start, end))
        reason_text = ", ".join(_reasons(fn, repeated))
        blocks.append(
            f"### Fonksiyon: {fn.name} (satir {fn.span.start_line}) — supphe nedeni: {reason_text}\n{snippet}"
        )

    return "\n\n".join(blocks)


def analyze_performance(
    source: str,
    facts: FileFacts,
    *,
    model: str = "gemini-3.6-flash",
    client: genai.Client | None = None,
) -> list[PerformanceFinding]:
    """FileFacts icindeki supheli fonksiyonlari performans acisindan LLM ile degerlendirir.

    Supheli fonksiyon yoksa hic LLM cagrisi yapmadan bos liste dondurur
    (maliyet tasarrufu, security_agent.py / clean_code_agent.py ile ayni desen).
    """
    suspicious = [
        fn for fn in facts.functions
        if _is_suspicious(fn, _calls_within(fn, facts.calls))
    ]
    if not suspicious:
        return []

    context = _build_context(source, facts, suspicious)
    client = client or genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    response = client.models.generate_content(
        model=model,
        contents=f"Dosya: {facts.path}\n\n{context}",
        config={
            "system_instruction": SYSTEM_PROMPT,
            "response_mime_type": "application/json",
        },
    )

    raw_text = response.text

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"LLM gecersiz JSON dondurdu: {raw_text}") from exc

    return [
        PerformanceFinding(
            function_name=f["function_name"],
            line=f["line"],
            category=f["category"],
            severity=f["severity"],
            is_real_issue=f["is_real_issue"],
            explanation=f["explanation"],
            suggestion=f["suggestion"],
        )
        for f in parsed.get("findings", [])
    ]