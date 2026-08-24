"""Security Agent — parser.py'den gelen FileFacts.calls listesindeki
riskli çağrıları LLM ile değerlendirip yapılandırılmış bulgular üretir.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from google import genai

from app.parser import FileFacts

SYSTEM_PROMPT = """Sen bir güvenlik statik analiz uzmanısın. Sana bir dosyadaki
riskli fonksiyon çağrılarının listesi ve o çağrıların bulunduğu kod satırları
verilecek. Her çağrı için gerçekten bir güvenlik açığı olup olmadığını
değerlendir (yanlış pozitifleri ele).

SADECE aşağıdaki JSON formatında cevap ver, başka hiçbir metin ekleme:

{
  "findings": [
    {
      "call_name": "eval",
      "line": 42,
      "severity": "high",
      "is_real_issue": true,
      "explanation": "Kullanıcı girdisi doğrudan eval() içine veriliyor, RCE riski var."
    }
  ]
}

severity: "low" | "medium" | "high" | "critical"
Eğer bir çağrı zararsızsa is_real_issue: false yap ve kısaca neden zararsız olduğunu açıkla.
"""


@dataclass(frozen=True, slots=True)
class SecurityFinding:
    call_name: str
    line: int
    severity: str
    is_real_issue: bool
    explanation: str


def _build_context(source: str, facts: FileFacts, context_lines: int = 3) -> str:
    """Her riskli çağrının etrafındaki birkaç satırı çıkarır (tüm dosyayı değil)."""
    lines = source.splitlines()
    blocks = []

    for call in facts.calls:
        if not call.risky:
            continue
        line_no = call.span.start_line
        start = max(0, line_no - 1 - context_lines)
        end = min(len(lines), line_no + context_lines)
        snippet = "\n".join(
            f"{i + 1}: {lines[i]}" for i in range(start, end)
        )
        blocks.append(
            f"### Çağrı: {call.name} (satır {line_no})\n{snippet}"
        )

    return "\n\n".join(blocks)


def analyze_security(
    source: str,
    facts: FileFacts,
    *,
    model: str = "gemini-2.0-flash",
    client: genai.Client | None = None,
) -> list[SecurityFinding]:
    """FileFacts içindeki riskli çağrıları LLM ile değerlendirir.

    Riskli çağrı yoksa hiç LLM çağrısı yapmadan boş liste döner (maliyet tasarrufu).
    """
    risky_calls = [c for c in facts.calls if c.risky]
    if not risky_calls:
        return []

    context = _build_context(source, facts)
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
        raise RuntimeError(f"LLM geçersiz JSON döndürdü: {raw_text}") from exc

    return [
        SecurityFinding(
            call_name=f["call_name"],
            line=f["line"],
            severity=f["severity"],
            is_real_issue=f["is_real_issue"],
            explanation=f["explanation"],
        )
        for f in parsed.get("findings", [])
    ]