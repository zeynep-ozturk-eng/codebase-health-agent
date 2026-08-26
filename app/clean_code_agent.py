"""Clean Code Agent — parser.py'den gelen FileFacts.functions/classes
listesindeki kod kalitesi sorunlarini LLM ile degerlendirip yapilandırılmıs
bulgular uretir.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from google import genai

from app.parser import FileFacts, Symbol

SYSTEM_PROMPT = """Sen bir clean code / kod kalitesi uzmanisin. Sana bir
dosyadaki süpheli fonksiyonlarin listesi ve o fonksiyonlarin kaynak kodu
verilecek. Her fonksiyon icin gerçekten bir clean code ihlali olup olmadigini
degerlendir (yanlis pozitifleri ele).

Degerlendirebilecegin kategoriler:
- long_function: fonksiyon cok uzun, tek sorumluluk ilkesini ihlal ediyor olabilir
- high_complexity: çok fazla dallanma/karar noktasi var, okunmasi zor
- too_many_params: parametre sayisi fazla, bir config/struct objesine tasinabilir
- deep_nesting: ic ice gecmis bloklar okunabilirligi dusuruyor
- poor_naming: isimlendirme anlamsiz veya yaniltici (orn. tek harfli, "data", "temp")
- duplicate_logic: fonksiyon icinde tekrar eden kod bloklari var

SADECE asagidaki JSON formatinda cevap ver, baska hicbir metin ekleme:

{
  "findings": [
    {
      "function_name": "process_data",
      "line": 42,
      "category": "long_function",
      "severity": "medium",
      "is_real_issue": true,
      "explanation": "Fonksiyon 120 satir ve 4 farkli is yapiyor: dogrulama, donustrume, kayit, bildirim.",
      "suggestion": "Bu dort sorumlulgu ayri fonksiyonlara bol."
    }
  ]
}

severity: "low" | "medium" | "high"
Eger metrikler kotu gorunse bile kod gerçekten sorunsuzsa (orn. uzun ama
tek bir mantiksal akisi olan bir switch-case), is_real_issue: false yap ve
kisaca neden sorun olmadigini acikla.
"""

# Eşikler: bu değerleri aşan fonksiyonlar LLM'e gönderilir
MAX_FUNCTION_LINES = 40
MAX_COMPLEXITY = 10
MAX_PARAMETERS = 5
MAX_NESTING = 4


@dataclass(frozen=True, slots=True)
class CleanCodeFinding:
    function_name: str
    line: int
    category: str
    severity: str
    is_real_issue: bool
    explanation: str
    suggestion: str


def _is_suspicious(fn: Symbol) -> bool:
    return (
        fn.line_count > MAX_FUNCTION_LINES
        or fn.complexity > MAX_COMPLEXITY
        or fn.parameter_count > MAX_PARAMETERS
        or fn.nesting > MAX_NESTING
    )


def _reasons(fn: Symbol) -> list[str]:
    """Fonksiyonun neden supheli işaretlendigini insanin okuyabilecegi sekilde listeler."""
    reasons = []
    if fn.line_count > MAX_FUNCTION_LINES:
        reasons.append(f"{fn.line_count} satir (esik: {MAX_FUNCTION_LINES})")
    if fn.complexity > MAX_COMPLEXITY:
        reasons.append(f"karmasiklik {fn.complexity} (esik: {MAX_COMPLEXITY})")
    if fn.parameter_count > MAX_PARAMETERS:
        reasons.append(f"{fn.parameter_count} parametre (esik: {MAX_PARAMETERS})")
    if fn.nesting > MAX_NESTING:
        reasons.append(f"nesting derinligi {fn.nesting} (esik: {MAX_NESTING})")
    return reasons


def _build_context(source: str, functions: list[Symbol]) -> str:
    """Sadece supheli fonksiyonlarin kaynak kodunu cikarir (tum dosyayi degil)."""
    lines = source.splitlines()
    blocks = []

    for fn in functions:
        start = max(0, fn.span.start_line - 1)
        end = min(len(lines), fn.span.end_line)
        snippet = "\n".join(f"{i + 1}: {lines[i]}" for i in range(start, end))
        reason_text = ", ".join(_reasons(fn))
        blocks.append(
            f"### Fonksiyon: {fn.name} (satir {fn.span.start_line}) — supheli nedeni: {reason_text}\n{snippet}"
        )

    return "\n\n".join(blocks)


def analyze_clean_code(
    source: str,
    facts: FileFacts,
    *,
    model: str = "gemini-3.6-flash",
    client: genai.Client | None = None,
) -> list[CleanCodeFinding]:
    """FileFacts.functions icindeki supheli fonksiyonlari LLM ile degerlendirir.

    Supheli fonksiyon yoksa hic LLM cagrisi yapmadan bos liste donderir
    (maliyet tasarrufu, security_agent.py ile ayni desen).
    """
    suspicious = [fn for fn in facts.functions if _is_suspicious(fn)]
    if not suspicious:
        return []

    context = _build_context(source, suspicious)
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
        raise RuntimeError(f"LLM gecersiz JSON dondu: {raw_text}") from exc

    return [
        CleanCodeFinding(
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