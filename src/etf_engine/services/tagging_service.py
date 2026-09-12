from collections import defaultdict
from datetime import date

# 核心权重股票的一级行业特征库 (覆盖各大宽基与行业核心重仓)
STOCK_INDUSTRY_MAP = {
    # 通信 / CPO / 算力网络
    "000063": "通信设备", "300308": "通信设备", "300502": "通信设备", "300394": "通信设备",
    "600522": "通信设备", "600487": "通信设备", "601138": "通信设备", "688036": "通信设备",
    "300136": "通信设备", "600941": "通信服务", "601728": "通信服务", "600050": "通信服务",
    # 电子 / 半导体芯片
    "688012": "半导体", "688981": "半导体", "603986": "半导体", "688256": "半导体",
    "603501": "半导体", "002049": "半导体", "688041": "半导体", "002371": "半导体",
    "688008": "半导体", "002475": "消费电子", "002241": "消费电子", "600745": "半导体",
    # 电力设备 / 新能源 / 光伏电池
    "300750": "电力设备", "601012": "电力设备", "300274": "电力设备", "600438": "电力设备",
    "300014": "电力设备", "688599": "电力设备", "601877": "电力设备", "002459": "电力设备",
    # 医药生物 / 创新药 / 医疗器械
    "600276": "医药生物", "300760": "医药生物", "300122": "医药生物", "300347": "医药生物",
    "600436": "医药生物", "000538": "医药生物", "688180": "医药生物", "688235": "医药生物",
    # 食品饮料 / 白酒
    "600519": "食品饮料", "000858": "食品饮料", "000568": "食品饮料", "600809": "食品饮料",
    "002304": "食品饮料", "603288": "食品饮料", "600887": "食品饮料", "000596": "食品饮料",
    # 大金融 / 银行 / 证券 / 保险
    "601318": "非银金融", "600030": "非银金融", "600036": "银行", "601166": "银行",
    "601288": "银行", "601398": "银行", "601988": "银行", "601939": "银行",
    "601628": "非银金融", "600837": "非银金融", "300059": "非银金融", "601688": "非银金融",
    # 有色金属 / 贵金属 / 资源
    "601899": "有色金属", "603993": "有色金属", "002460": "有色金属", "600547": "有色金属",
    "601600": "有色金属", "600111": "有色金属", "600489": "有色金属", "000878": "有色金属",
    # 汽车 / 智能整车
    "002594": "汽车", "600104": "汽车", "601238": "汽车", "601633": "汽车", "601689": "汽车",
    # 计算机 / 软件 / AI
    "002230": "计算机", "600588": "计算机", "601360": "计算机", "300496": "计算机",
    "688111": "计算机", "300033": "计算机", "600570": "计算机", "002410": "计算机",
}

# 备用名称关键词映射
KEYWORD_RULES = [
    ("通信|光模块|中兴|旭创|新易盛|天孚", "通信设备"),
    ("半导体|芯片|微电子|集成电路|北方华创|中微", "半导体"),
    ("电池|光伏|新能源|阳光电源|隆基|通威|宁德", "电力设备"),
    ("药|生物|医疗|迈瑞|恒瑞|百济|药明", "医药生物"),
    ("酒|饮料|食品|茅台|五粮液|泸州|汾酒", "食品饮料"),
    ("银行|工行|建行|农行|招行|中行", "银行"),
    ("证券|保险|中信|华泰|海通|平安|太保", "非银金融"),
    ("铝|铜|金|矿业|稀土|有色|紫金|洛阳钼业", "有色金属"),
    ("车|比亚迪|长城|上汽|长安", "汽车"),
    ("软件|计算机|科大讯飞|金山|同花顺", "计算机"),
]


class TaggingService:
    @staticmethod
    def infer_stock_industry(stock_id: str, stock_name: str | None) -> str:
        pure_code = stock_id.split(".")[0]
        if pure_code in STOCK_INDUSTRY_MAP:
            return STOCK_INDUSTRY_MAP[pure_code]
        if stock_name:
            for pattern, ind in KEYWORD_RULES:
                import re
                if re.search(pattern, stock_name):
                    return ind
        return "其他"

    def calculate_industry_tags(self, etf_id: str, holdings: list[dict], asof_date: date | None = None) -> list[dict]:
        """按持仓权重穿透加权，计算 ETF 的行业暴露标签。"""
        if not holdings:
            return []

        industry_weights = defaultdict(float)
        total_weight = 0.0

        for h in holdings:
            stock_id = h["stock_id"]
            stock_name = h.get("stock_name")
            weight = float(h.get("weight_pct") or 0.0)
            if weight <= 0:
                continue

            ind = self.infer_stock_industry(stock_id, stock_name)
            industry_weights[ind] += weight
            total_weight += weight

        if total_weight <= 0:
            return []

        # 排序行业权重
        sorted_industries = sorted(industry_weights.items(), key=lambda x: x[1], reverse=True)
        top1_ind, top1_weight = sorted_industries[0]

        tags: list[dict] = []
        top1_ratio = top1_weight / total_weight

        # 若最大行业占比 >= 30%，则该行业为主要行业标签
        if top1_ratio >= 0.30 and top1_ind != "其他":
            tags.append(
                {
                    "etf_id": etf_id,
                    "tag": top1_ind,
                    "tag_type": "industry",
                    "confidence": round(top1_ratio, 4),
                    "source": "holding_penetration",
                    "valid_from": asof_date,
                }
            )

        # 若第二大行业占比 >= 18%，也作为次要行业标签
        if len(sorted_industries) > 1:
            top2_ind, top2_weight = sorted_industries[1]
            top2_ratio = top2_weight / total_weight
            if top2_ratio >= 0.18 and top2_ind != "其他":
                tags.append(
                    {
                        "etf_id": etf_id,
                        "tag": top2_ind,
                        "tag_type": "industry",
                        "confidence": round(top2_ratio, 4),
                        "source": "holding_penetration",
                        "valid_from": asof_date,
                    }
                )

        # 若前十大持仓分散度很高（各行业均 < 30% 且至少跨 3 个行业），打标为宽基/均衡配置
        if top1_ratio < 0.30 and len([k for k in industry_weights if k != "其他"]) >= 3:
            tags.append(
                {
                    "etf_id": etf_id,
                    "tag": "核心宽基/均衡",
                    "tag_type": "style",
                    "confidence": 0.85,
                    "source": "holding_penetration",
                    "valid_from": asof_date,
                }
            )

        return tags
