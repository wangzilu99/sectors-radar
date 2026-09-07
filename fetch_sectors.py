#!/usr/bin/env python3
"""
题材行情拉取脚本

用法：
  python3 fetch_sectors.py us   # 拉美股（22次，约5分钟）
  python3 fetch_sectors.py cn   # 拉A股（新浪财经，无限制，约10秒）

两个 Alpha Vantage Key 自动轮询，合计 50次/天，一天内可同时拉两个市场。

crontab 配置（crontab -e，路径换成你实际的）：
  # 美股：每天 08:00
  0 8 * * * cd ~/Desktop/sectors && python3 fetch_sectors.py us >> fetch_us.log 2>&1

  # A股：工作日交易时间每 10 分钟（9:30-11:30 和 13:00-15:00）
  */10 9 * * 1-5 cd ~/Desktop/sectors && python3 fetch_sectors.py cn >> fetch_cn.log 2>&1
  */10 10 * * 1-5 cd ~/Desktop/sectors && python3 fetch_sectors.py cn >> fetch_cn.log 2>&1
  20,30,40,50 11 * * 1-5 cd ~/Desktop/sectors && python3 fetch_sectors.py cn >> fetch_cn.log 2>&1
  0,10,20,30,40,50 13 * * 1-5 cd ~/Desktop/sectors && python3 fetch_sectors.py cn >> fetch_cn.log 2>&1
  */10 14 * * 1-5 cd ~/Desktop/sectors && python3 fetch_sectors.py cn >> fetch_cn.log 2>&1
  0 15 * * 1-5 cd ~/Desktop/sectors && python3 fetch_sectors.py cn >> fetch_cn.log 2>&1
"""

import json, time, sys, os, urllib.request, re
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Alpha Vantage：两个 Key 轮询，每天合计 50 次配额 ──
AV_KEYS   = ['7WPA9V1S2FY7482L', 'SD42Y3USGQ4DLABB']
AV_DELAY  = 13   # 秒，每次请求间隔（保持 ≤5次/分钟）

# us 用第一个 Key，cn 用第二个 Key，互不干扰各自 25次/天
AV_KEY_US = AV_KEYS[0]
AV_KEY_CN = AV_KEYS[1]  # 预留给未来美股扩展用，当前 A股走新浪

# ──────────────────────────────────────────
#  板块定义
# ──────────────────────────────────────────
US_SECTORS = [
    {'name':'数字货币',  'icon':'🏛️', 'sym':'BITO' },
    {'name':'AI应用',   'icon':'✨',  'sym':'AIQ'  },
    {'name':'核电',     'icon':'☢️',  'sym':'URA'  },
    {'name':'商业航天', 'icon':'🚀',  'sym':'ARKX' },
    {'name':'银行/金融','icon':'🏦',  'sym':'XLF'  },
    {'name':'AI安全',   'icon':'🔐',  'sym':'BUG'  },
    {'name':'汽车',     'icon':'🚙',  'sym':'DRIV' },
    {'name':'有色金属', 'icon':'🟡',  'sym':'XME'  },
    {'name':'跨境支付', 'icon':'💳',  'sym':'IPAY' },
    {'name':'稀土永磁', 'icon':'🧲',  'sym':'REMX' },
    {'name':'电力',     'icon':'🔌',  'sym':'XLU'  },
    {'name':'军工',     'icon':'🛡️',  'sym':'ITA'  },
    {'name':'油气',     'icon':'🛢️',  'sym':'XLE'  },
    {'name':'AI算力',   'icon':'🖥️',  'sym':'NVDA' },
    {'name':'零售',     'icon':'🛒',  'sym':'XRT'  },
    {'name':'医药',     'icon':'💊',  'sym':'IBB'  },
    {'name':'光伏',     'icon':'☀️',  'sym':'TAN'  },
    {'name':'化工',     'icon':'🧪',  'sym':'XLB'  },
    {'name':'食品饮料', 'icon':'🍽️',  'sym':'XLP'  },
    {'name':'半导体',   'icon':'💿',  'sym':'SOXX' },
    {'name':'存储芯片', 'icon':'💾',  'sym':'MU'   },
    {'name':'光通信',   'icon':'💡',  'sym':'FIVG' },
]

CN_SECTORS = [
    {'name':'半导体',   'icon':'💿',  'sym':'sh512480'},
    {'name':'AI应用',   'icon':'✨',  'sym':'sh515070'},
    {'name':'新能源车', 'icon':'⚡',  'sym':'sz159995'},
    {'name':'光伏',     'icon':'☀️',  'sym':'sh515790'},
    {'name':'储能',     'icon':'🔋',  'sym':'sh561910'},
    {'name':'医药',     'icon':'💊',  'sym':'sh512010'},
    {'name':'消费',     'icon':'🛍️',  'sym':'sz159928'},
    {'name':'食品饮料', 'icon':'🍽️',  'sym':'sh515170'},
    {'name':'军工',     'icon':'🛡️',  'sym':'sh512660'},
    {'name':'金融',     'icon':'🏦',  'sym':'sh510230'},
    {'name':'地产',     'icon':'🏢',  'sym':'sh512200'},
    {'name':'有色金属', 'icon':'🟡',  'sym':'sh512400'},
    {'name':'化工',     'icon':'🧪',  'sym':'sh516020'},
    {'name':'科技互联', 'icon':'💻',  'sym':'sh515030'},
]

# ──────────────────────────────────────────
#  美股：Alpha Vantage TIME_SERIES_DAILY
# ──────────────────────────────────────────
def fetch_us_one(sym, api_key):
    url = (f'https://www.alphavantage.co/query'
           f'?function=TIME_SERIES_DAILY&symbol={sym}'
           f'&outputsize=compact&apikey={api_key}')
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read())

    if 'Note' in data or 'Information' in data:
        raise RuntimeError('RATE_LIMIT')

    series = data.get('Time Series (Daily)', {})
    if not series:
        raise RuntimeError('NO_DATA')

    dates  = sorted(series.keys(), reverse=True)[:6]
    closes = [float(series[d]['4. close']) for d in dates]
    if len(closes) < 2:
        raise RuntimeError('INSUFFICIENT')

    chg1d = (closes[0] - closes[1]) / closes[1] * 100
    days  = min(5, len(closes) - 1)
    chg5d = (closes[0] - closes[days]) / closes[days] * 100
    spark = list(reversed(closes[:min(5, len(closes))]))
    return round(chg1d, 3), round(chg5d, 3), [round(x, 4) for x in spark]


def run_us():
    total   = len(US_SECTORS)
    results = []
    success = 0
    # 两个 Key 交替使用：偶数索引用 Key1，奇数索引用 Key2
    # 这样每个 Key 各用约 11 次，远低于 25次/天限制
    keys = AV_KEYS

    print(f'\n▶ 美股 ({total} 个板块)  开始: {datetime.now().strftime("%H:%M:%S")}')
    print(f'  使用 {len(keys)} 个 API Key 交替请求')

    for i, s in enumerate(US_SECTORS):
        api_key = keys[i % len(keys)]
        try:
            chg1d, chg5d, spark = fetch_us_one(s['sym'], api_key)
            results.append({**s, 'chg1d': chg1d, 'chg5d': chg5d, 'spark': spark})
            print(f'  [{i+1:2d}/{total}] {s["name"]:6s} ({s["sym"]:5s}) '
                  f'今日 {chg1d:+.2f}%  5日 {chg5d:+.2f}%  [Key{i%2+1}]')
            success += 1
        except RuntimeError as e:
            if 'RATE_LIMIT' in str(e):
                # 尝试切换到另一个 Key
                other_key = keys[(i + 1) % len(keys)]
                print(f'  [{i+1:2d}/{total}] Key{i%2+1} 配额耗尽，切换到另一个 Key...')
                try:
                    chg1d, chg5d, spark = fetch_us_one(s['sym'], other_key)
                    results.append({**s, 'chg1d': chg1d, 'chg5d': chg5d, 'spark': spark})
                    print(f'  [{i+1:2d}/{total}] {s["name"]:6s} ({s["sym"]:5s}) '
                          f'今日 {chg1d:+.2f}%  5日 {chg5d:+.2f}%  [Key 切换]')
                    success += 1
                    continue
                except RuntimeError:
                    print(f'  两个 Key 配额均耗尽，停止')
                    results.append({**s, 'chg1d': None, 'chg5d': None, 'spark': []})
                    break
            print(f'  [{i+1:2d}/{total}] {s["sym"]} ✗  {e}')
            results.append({**s, 'chg1d': None, 'chg5d': None, 'spark': []})
        except Exception as e:
            print(f'  [{i+1:2d}/{total}] {s["sym"]} ✗  {e}')
            results.append({**s, 'chg1d': None, 'chg5d': None, 'spark': []})

        if i < total - 1:
            time.sleep(AV_DELAY)

    print(f'  完成: {success}/{total}  结束: {datetime.now().strftime("%H:%M:%S")}')
    save('us_sectors_data.json', 'us', results)

# ──────────────────────────────────────────
#  A股：新浪财经（无限制，无需 API Key）
# ──────────────────────────────────────────
SINA_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
    'Referer':    'https://finance.sina.com.cn',
}

def fetch_cn_realtime(sym):
    url = f'https://hq.sinajs.cn/list={sym}'
    req = urllib.request.Request(url, headers=SINA_HEADERS)
    with urllib.request.urlopen(req, timeout=10) as r:
        raw = r.read().decode('gbk', errors='replace')

    m = re.search(r'"([^"]+)"', raw)
    if not m:
        raise RuntimeError('PARSE_ERROR')

    fields = m.group(1).split(',')
    if len(fields) < 4:
        raise RuntimeError('INSUFFICIENT_FIELDS')

    # 字段: 0=名称, 1=今开, 2=昨收, 3=当前价
    prev_close = float(fields[2])
    current    = float(fields[3])
    if prev_close == 0:
        raise RuntimeError('ZERO_PRICE')
    return round((current - prev_close) / prev_close * 100, 3)


def fetch_cn_history(sym):
    url = (f'https://quotes.sina.cn/cn/api/jsonp_v2.php/var='
           f'/CN_MarketDataService.getKLineData'
           f'?symbol={sym}&scale=240&datalen=6')
    req = urllib.request.Request(url, headers=SINA_HEADERS)
    with urllib.request.urlopen(req, timeout=10) as r:
        raw = r.read().decode('utf-8', errors='replace')

    # JSONP 格式: /*...*/ var=([{...},...]);
    m = re.search(r'\(\[(.*)\]\)', raw, re.DOTALL)
    if not m:
        raise RuntimeError('PARSE_ERROR')

    items = json.loads('[' + m.group(1) + ']')
    if not items or len(items) < 2:
        raise RuntimeError('INSUFFICIENT_HISTORY')

    items  = sorted(items, key=lambda x: x.get('day', ''))
    closes = [float(x['close']) for x in items]
    days   = min(5, len(closes) - 1)
    chg5d  = (closes[-1] - closes[-1 - days]) / closes[-1 - days] * 100
    spark  = closes[-5:]
    return round(chg5d, 3), [round(x, 4) for x in spark]


def run_cn():
    total   = len(CN_SECTORS)
    results = []
    success = 0

    print(f'\n▶ A股 ({total} 个板块)  开始: {datetime.now().strftime("%H:%M:%S")}')

    for i, s in enumerate(CN_SECTORS):
        sym   = s['sym']
        chg1d, chg5d, spark = None, None, []

        try:
            chg1d = fetch_cn_realtime(sym)
        except Exception as e:
            print(f'  [{i+1:2d}/{total}] {s["name"]:6s} ({sym}) 实时失败: {e}')

        try:
            chg5d, spark = fetch_cn_history(sym)
        except Exception as e:
            print(f'  [{i+1:2d}/{total}] {s["name"]:6s} ({sym}) 历史失败: {e}')

        if chg1d is not None:
            success += 1
            print(f'  [{i+1:2d}/{total}] {s["name"]:6s} ({sym}) '
                  f'今日 {chg1d:+.2f}%'
                  + (f'  5日 {chg5d:+.2f}%' if chg5d is not None else ''))
        else:
            print(f'  [{i+1:2d}/{total}] {s["name"]:6s} ({sym}) ✗')

        results.append({**s, 'chg1d': chg1d, 'chg5d': chg5d, 'spark': spark})
        time.sleep(0.5)

    print(f'  完成: {success}/{total}  结束: {datetime.now().strftime("%H:%M:%S")}')
    save('cn_sectors_data.json', 'cn', results)

# ──────────────────────────────────────────
#  写入 JSON
# ──────────────────────────────────────────
def save(filename, market_key, sectors_data):
    path = os.path.join(SCRIPT_DIR, filename)
    payload = {
        'market':     market_key,
        'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'updated_ts': int(time.time() * 1000),
        'sectors':    sectors_data,
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    ok = sum(1 for s in sectors_data if s['chg1d'] is not None)
    print(f'  ✅ 写入 {path}  ({ok}/{len(sectors_data)} 有效)')

# ──────────────────────────────────────────
#  入口
# ──────────────────────────────────────────
def main():
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else 'help'
    if mode == 'us':
        run_us()
    elif mode == 'cn':
        run_cn()
    elif mode == 'all':
        run_us()
        run_cn()
    else:
        print(__doc__)
        sys.exit(1)

if __name__ == '__main__':
    main()
