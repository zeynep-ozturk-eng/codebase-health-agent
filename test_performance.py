"""performance_agent.py icin hizli test scripti."""

from dotenv import load_dotenv
load_dotenv()

from app.parser import parse_source
from app.performance_agent import analyze_performance

# Kasten donguide N+1 sorgu paterni iceren ornek kod
test_source_1 = '''
def get_order_summaries(order_ids):
    summaries = []
    for order_id in order_ids:
        order = db.query(order_id)
        customer = db.query(order.customer_id)
        items = db.query(order.item_ids)
        summaries.append({
            "order": order,
            "customer": customer,
            "items": items,
        })
    return summaries
'''

test_source_2='''
def find_duplicates(matrix):
    duplicates=[]
    for i in range(len(matrix)):
        for j in range(len(matrix)):
            for k in range(len(matrix)):
                if matrix[i]==matrix[j]==matrix[k] and i !=j !=k:
                    duplicates.append(matrix[i])
                    return duplicates
'''
facts_1 = parse_source(test_source_1, path="test.py", language="python")

print(f"Bulunan fonksiyon sayisi: {len(facts_1.functions)}")
for fn in facts_1.functions:
    print(f"  {fn.name}: {fn.line_count} satir, karmasiklik={fn.complexity}, nesting={fn.nesting}")

print(f"\nToplam cagri sayisi: {len(facts_1.calls)}")
for c in facts_1.calls:
    print(f"  {c.name} (satir {c.span.start_line})")

findings_1 = analyze_performance(test_source_1, facts_1)

print(f"\nBulgu sayisi: {len(findings_1)}")
for f in findings_1:
    print(f"\n- Fonksiyon: {f.function_name} (satir {f.line})")
    print(f"  Kategori: {f.category} | Onem: {f.severity} | Gercek sorun mu: {f.is_real_issue}")
    print(f"  Aciklama: {f.explanation}")
    print(f"  Oneri: {f.suggestion}")

print("\n"+ "="*30)
print("Senaryo 2: nested loops")
print("="*30)

facts_2 = parse_source(test_source_2, path="test.py", language="python")

print(f"Bulunan fonksiyon sayisi: {len(facts_2.functions)}")
for fn in facts_2.functions:
    print(f"  {fn.name}: {fn.line_count} satir, karmasiklik={fn.complexity}, nesting={fn.nesting}")

print(f"\nToplam cagri sayisi: {len(facts_2.calls)}")
for c in facts_2.calls:
    print(f"  {c.name} (satir {c.span.start_line})")

findings_2 = analyze_performance(test_source_2, facts_2)
print(f"Bulgu sayisi: {len(findings_2)}")
for f in findings_2:
   print(f"\n- Fonksiyon: {f.function_name} (satir {f.line})")
   print(f"  Kategori: {f.category} | Onem: {f.severity} | Gercek mi: {f.is_real_issue}")
   print(f"  Aciklama: {f.explanation}")
   print(f"  Oneri: {f.suggestion}")

    