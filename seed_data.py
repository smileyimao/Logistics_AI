"""Run once to seed mock data: python3 seed_data.py"""
import sqlite3, random, datetime

DB = "shipments.db"
conn = sqlite3.connect(DB)

channels  = ["大陆UPS红单_6000", "香港UPS红单_5800", "大陆DHL_A价", "大陆联邦IP_5000", "香港DHL直发"]
agents    = ["UPS", "DHL", "FedEx", "联邦", "顺丰跨境"]
countries = ["美国", "加拿大", "英国", "德国", "澳大利亚", "法国", "日本", "墨西哥"]
postcodes = ["95035","V6B2P6","EC1A1BB","10115","2000","75001","1000001","06600"]
customers = ["苹果贸易公司","深圳汇丰电子","广州明威科技","上海锦程物流","北京星辰跨境","成都天府贸易","东莞优品出口","杭州西湖电商"]
salesmen  = ["张明","李华","王芳","陈伟","刘洋","赵磊","孙丽","周强"]
methods   = ["转账","微信","支付宝","现金","银行汇款"]
sources   = ["web","bot","web","web","bot"]

def rand_date(days_ago_max=180):
    d = datetime.datetime.now() - datetime.timedelta(
        days=random.randint(0, days_ago_max),
        hours=random.randint(0,23), minutes=random.randint(0,59))
    return d.strftime("%Y-%m-%d %H:%M:%S")

def rand_weight(): return round(random.uniform(0.5, 50), 3)
def rand_money():  return round(random.uniform(200, 8000), 2)
def rand_no(prefix="SH"): return prefix + str(random.randint(10000000, 99999999))

rows = []
for i in range(30):
    ci = random.randint(0, len(countries)-1)
    aw = rand_weight()
    tw = round(aw * random.uniform(1, 1.3), 3)
    sw = round(tw * random.uniform(0.9, 1.1), 3)
    pr = rand_money()
    pa = round(pr * random.uniform(0.5, 0.85), 2)
    gp = round(pr - pa - random.uniform(0, 300), 2)
    rows.append({
        "tracking_no":      rand_no("XCST"),
        "transfer_no":      rand_no("XL2026"),
        "salesperson":      random.choice(salesmen),
        "customer":         random.choice(customers),
        "channel":          random.choice(channels),
        "destination":      countries[ci],
        "postal_code":      postcodes[ci % len(postcodes)],
        "payment_received": pr,
        "payment_slip":     "水单" + str(random.randint(100,999)) if random.random()>0.4 else "",
        "payment_method":   random.choice(methods),
        "invoiced":         random.choice(["是","否"]),
        "payment_amount":   pa,
        "is_paid":          random.choice(["是","否","部分"]),
        "misc_fee":         round(random.uniform(0, 500), 2) if random.random()>0.5 else "",
        "remarks":          random.choice(["正常出货","客户要求加急","待确认重量","已付清","特批出货",""]),
        "insurance":        random.choice(["是","否"]),
        "actual_weight":    aw,
        "volume":           round(aw * random.uniform(0.6, 1.2), 3),
        "total_weight":     tw,
        "pieces":           random.randint(1, 20),
        "ship_weight":      sw,
        "gross_profit":     gp,
        "profit_rate":      str(round(gp/pr*100, 1)) + "%" if pr else "",
        "agent":            random.choice(agents),
        "wooden_frame":     random.choice(["是","否",""]),
        "has_docs":         random.choice(["是","否"]),
        "ship_date":        rand_date(30)[:10],
        "source":           random.choice(sources),
        "created_by":       random.choice(salesmen),
        "created_at":       rand_date(),
    })

cols = list(rows[0].keys())
placeholders = ",".join(["?"]*len(cols))
col_names = ",".join(cols)
conn.executemany(
    f"INSERT INTO shipments ({col_names}) VALUES ({placeholders})",
    [[r[c] for c in cols] for r in rows]
)
conn.commit()
conn.close()
print(f"✅ 插入 {len(rows)} 条模拟数据完成")
