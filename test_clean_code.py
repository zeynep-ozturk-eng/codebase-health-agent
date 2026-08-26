"""clean_code_agent.py icin hizli test scripti."""

from dotenv import load_dotenv
load_dotenv()

from app.parser import parse_source
from app.clean_code_agent import analyze_clean_code

# Kasten uzun, karmasik, cok parametreli bir fonksiyon iceren ornek kod
test_source = '''
def process_user_order(user_id, order_id, discount_code, shipping_address, billing_address, payment_method):
    if user_id is None:
        return None
    if order_id is None:
        return None
    total = 0
    for item in range(10):
        if item % 2 == 0:
            if item > 5:
                total += item * 2
            else:
                total += item
        else:
            if item < 3:
                total -= item
            else:
                total += 1
    if discount_code == "SAVE10":
        total = total * 0.9
    elif discount_code == "SAVE20":
        total = total * 0.8
    if shipping_address is None:
        shipping_address = billing_address
    return total
'''

facts = parse_source(test_source, path="test.py", language="python")

print(f"Bulunan fonksiyon sayisi: {len(facts.functions)}")
for fn in facts.functions:
    print(f"  {fn.name}: {fn.line_count} satir, karmasiklik={fn.complexity}, parametre={fn.parameter_count}, nesting={fn.nesting}")

findings = analyze_clean_code(test_source, facts)

print(f"\nBulgu sayisi: {len(findings)}")
for f in findings:
    print(f"\n- Fonksiyon: {f.function_name} (satir {f.line})")
    print(f"  Kategori: {f.category} | Onem: {f.severity} | Gercek sorun mu: {f.is_real_issue}")
    print(f"  Aciklama: {f.explanation}")
    print(f"  Oneri: {f.suggestion}")