#!/usr/bin/env python3
"""
题材行情拉取脚本

用法：
  python3 fetch_sectors.py us   # 美股板块 + 大盘 + 新闻（约5分钟）
  python3 fetch_sectors.py cn   # A股板块 + 大盘（约15秒）

GitHub Actions / crontab 自动执行：
  美股：每天 08:00（北京时间）
  A股：工作日交易时间每 10 分钟
"""

import json, time, sys, os, urllib.request, re
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

AV_KEYS  = [
    os.environ.get('AV_KEY_1', '7WPA9V1S2FY7482L'),
    os.environ.get('AV_KEY_2', 'SD42Y3USGQ4DLABB'),
]
AV_DELAY = 13

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

US_INDEX = [
    {'name':'标普500', 'icon':'🇺🇸', 'sym':'SPY' },
    {'name':'纳斯达克','icon':'💻',  'sym':'QQQ' },
    {'name':'道琼斯',  'icon':'🏛️', 'sym':'DIA' },
    {'name':'小盘股',  'icon':'📊',  'sym':'IWM' },
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

CN_INDEX = [
    {'name':'上证指数', 'icon':'🇨🇳', 'sym':'sh000001'},
    {'name':'深证成指', 'icon':'📈',  'sym':'sz399001'},
    {'name':'创业板',   'icon':'🚀',  'sym':'sz399006'},
    {'name':'沪深300',  'icon':'📊',  'sym':'sh000300'},
    {'name':'科创50',   'icon':'🔬',  'sym':'sh000688'},
]

# ──────────────────────────────────────────
#  Alpha Vantage：行情
# ──────────────────────────────────────────
def fetch_av_daily(sym, api_key):
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
    return round(chg1d, 3), round(chg5d, 3), [round(x, 4) for x in spark], round(closes[0], 4)

# ──────────────────────────────────────────
#  Alpha Vantage：新闻
# ──────────────────────────────────────────
SENTIMENT_SCORE = {
    'Bearish': -2, 'Somewhat-Bearish': -1,
    'Neutral': 0,
    'Somewhat-Bullish': 1, 'Bullish': 2,
}

def fetch_news(api_key):
    url = (f'https://www.alphavantage.co/query'
           f'?function=NEWS_SENTIMENT'
           f'&topics=economy,geopolitics,technology,finance'
           f'&sort=RELEVANCE&limit=50'
           f'&apikey={api_key}')
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read())
    if 'Note' in data or 'Information' in data:
        raise RuntimeError('RATE_LIMIT')

    feed = data.get('feed', [])
    # 只保留情绪明确（非 Neutral / Somewhat）的
    strong = [
        item for item in feed
        if item.get('overall_sentiment_label') in ('Bullish', 'Bearish')
    ]
    # 取前5条，按 relevance_score 排序
    strong.sort(key=lambda x: float(x.get('relevance_score', 0)), reverse=True)
    result = []
    for item in strong[:5]:
        label = item.get('overall_sentiment_label', 'Neutral')
        result.append({
            'title':     item.get('title', ''),
            'url':       item.get('url', ''),
            'source':    item.get('source', ''),
            'sentiment': label,
            'score':     SENTIMENT_SCORE.get(label, 0),
            'time':      item.get('time_published', '')[:12],  # YYYYMMDDHHmm
        })
    return result

# ──────────────────────────────────────────
#  新浪财经：实时 + 历史
# ──────────────────────────────────────────
SINA_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
    'Referer':    'https://finance.sina.com.cn',
}

def fetch_sina_realtime(sym):
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
    prev  = float(fields[2])
    curr  = float(fields[3])
    if prev == 0:
        raise RuntimeError('ZERO_PRICE')
    return round((curr - prev) / prev * 100, 3), round(curr, 4)

def fetch_sina_history(sym):
    url = (f'https://quotes.sina.cn/cn/api/jsonp_v2.php/var='
           f'/CN_MarketDataService.getKLineData'
           f'?symbol={sym}&scale=240&datalen=6')
    req = urllib.request.Request(url, headers=SINA_HEADERS)
    with urllib.request.urlopen(req, timeout=10) as r:
        raw = r.read().decode('utf-8', errors='replace')
    m = re.search(r'\(\[(.*)\]\)', raw, re.DOTALL)
    if not m:
        raise RuntimeError('PARSE_ERROR')
    items  = sorted(json.loads('[' + m.group(1) + ']'), key=lambda x: x.get('day', ''))
    closes = [float(x['close']) for x in items]
    if len(closes) < 2:
        raise RuntimeError('INSUFFICIENT')
    days  = min(5, len(closes) - 1)
    chg5d = (closes[-1] - closes[-1-days]) / closes[-1-days] * 100
    return round(chg5d, 3), [round(x, 4) for x in closes[-5:]]

# ──────────────────────────────────────────
#  Run US
# ──────────────────────────────────────────
def run_us():
    keys    = AV_KEYS
    results = []
    success = 0

    # 1. 板块（22个，两个 Key 交替）
    total = len(US_SECTORS)
    print(f'\n▶ 美股板块 ({total})  开始: {datetime.now().strftime("%H:%M:%S")}')
    for i, s in enumerate(US_SECTORS):
        api_key = keys[i % len(keys)]
        chg1d = chg5d = None; spark = []; price = None
        try:
            chg1d, chg5d, spark, price = fetch_av_daily(s['sym'], api_key)
            success += 1
            print(f'  [{i+1:2d}/{total}] {s["name"]:6s} ({s["sym"]:5s}) 今日 {chg1d:+.2f}%  5日 {chg5d:+.2f}%')
        except RuntimeError as e:
            if 'RATE_LIMIT' in str(e):
                other = keys[(i+1) % len(keys)]
                try:
                    chg1d, chg5d, spark, price = fetch_av_daily(s['sym'], other)
                    success += 1
                    print(f'  [{i+1:2d}/{total}] {s["name"]:6s} 切换Key 今日 {chg1d:+.2f}%')
                except: print(f'  [{i+1:2d}/{total}] {s["sym"]} ✗ 两Key均限额')
            else:
                print(f'  [{i+1:2d}/{total}] {s["sym"]} ✗ {e}')
        except Exception as e:
            print(f'  [{i+1:2d}/{total}] {s["sym"]} ✗ {e}')
        results.append({**s, 'chg1d': chg1d, 'chg5d': chg5d, 'spark': spark, 'price': price})
        if i < total - 1: time.sleep(AV_DELAY)

    # 2. 大盘指数（4个，用剩余 Key）
    index_results = []
    print(f'\n▶ 美股大盘 ({len(US_INDEX)})')
    for i, s in enumerate(US_INDEX):
        api_key = keys[i % len(keys)]
        chg1d = chg5d = None; spark = []; price = None
        try:
            chg1d, chg5d, spark, price = fetch_av_daily(s['sym'], api_key)
            print(f'  {s["name"]:6s} ({s["sym"]}) 今日 {chg1d:+.2f}%  5日 {chg5d:+.2f}%')
        except Exception as e:
            print(f'  {s["sym"]} ✗ {e}')
        index_results.append({**s, 'chg1d': chg1d, 'chg5d': chg5d, 'spark': spark, 'price': price})
        if i < len(US_INDEX) - 1: time.sleep(AV_DELAY)

    # 3. 新闻（1次调用）
    news = []
    print(f'\n▶ 市场新闻')
    try:
        news = fetch_news(keys[0])
        print(f'  获取 {len(news)} 条关键新闻')
        for n in news:
            print(f'  [{n["sentiment"]}] {n["title"][:70]}')
    except Exception as e:
        print(f'  新闻获取失败: {e}')

    # 4. 写入
    payload = {
        'market':     'us',
        'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'updated_ts': int(time.time() * 1000),
        'sectors':    results,
        'index':      index_results,
        'news':       news,
    }
    path = os.path.join(SCRIPT_DIR, 'us_sectors_data.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f'\n  ✅ 写入 {path}  板块 {success}/{total}')

# ──────────────────────────────────────────
#  Run CN
# ──────────────────────────────────────────
def run_cn():
    results = []
    success = 0

    # 1. 板块
    total = len(CN_SECTORS)
    print(f'\n▶ A股板块 ({total})  开始: {datetime.now().strftime("%H:%M:%S")}')
    for i, s in enumerate(CN_SECTORS):
        sym = s['sym']
        chg1d = chg5d = None; spark = []; price = None
        try:
            chg1d, price = fetch_sina_realtime(sym)
        except Exception as e:
            print(f'  [{i+1:2d}/{total}] {s["name"]:6s} ({sym}) 实时失败: {e}')
        try:
            chg5d, spark = fetch_sina_history(sym)
        except Exception as e:
            print(f'  [{i+1:2d}/{total}] {s["name"]:6s} ({sym}) 历史失败: {e}')
        if chg1d is not None:
            success += 1
            print(f'  [{i+1:2d}/{total}] {s["name"]:6s} ({sym}) 今日 {chg1d:+.2f}%' +
                  (f'  5日 {chg5d:+.2f}%' if chg5d else ''))
        else:
            print(f'  [{i+1:2d}/{total}] {s["name"]:6s} ({sym}) ✗')
        results.append({**s, 'chg1d': chg1d, 'chg5d': chg5d, 'spark': spark, 'price': price})
        time.sleep(0.3)

    # 2. 大盘指数
    index_results = []
    print(f'\n▶ A股大盘 ({len(CN_INDEX)})')
    for s in CN_INDEX:
        sym = s['sym']
        chg1d = chg5d = None; spark = []; price = None
        try:
            chg1d, price = fetch_sina_realtime(sym)
        except Exception as e:
            print(f'  {s["name"]} ({sym}) 实时失败: {e}')
        try:
            chg5d, spark = fetch_sina_history(sym)
        except Exception as e:
            print(f'  {s["name"]} ({sym}) 历史失败: {e}')
        if chg1d is not None:
            print(f'  {s["name"]:6s} ({sym}) 今日 {chg1d:+.2f}%' +
                  (f'  5日 {chg5d:+.2f}%' if chg5d else ''))
        index_results.append({**s, 'chg1d': chg1d, 'chg5d': chg5d, 'spark': spark, 'price': price})
        time.sleep(0.3)

    # 3. 写入
    payload = {
        'market':     'cn',
        'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'updated_ts': int(time.time() * 1000),
        'sectors':    results,
        'index':      index_results,
    }
    path = os.path.join(SCRIPT_DIR, 'cn_sectors_data.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f'\n  ✅ 写入 {path}  板块 {success}/{total}')

# ──────────────────────────────────────────
def main():
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else 'help'
    if   mode == 'us':  run_us()
    elif mode == 'cn':  run_cn()
    elif mode == 'all': run_us(); run_cn()
    else: print(__doc__); sys.exit(1)

if __name__ == '__main__':
    main()
