# -*- coding: utf-8 -*-
"""合併第一版(zh_tw.CODE)與第二版(zh_v2_map.json:對戰提示/效果名稱/效果說明…)的程式字串常值對照表。
第二版檔案不存在時,就只有第一版。"""
import json
import os

import zh_tw

S = os.path.dirname(os.path.abspath(__file__))
V2_PATH = os.path.join(S, "zh_v2_map.json")

ALL = dict(zh_tw.CODE)
V2 = {}
if os.path.exists(V2_PATH):
    V2 = json.load(open(V2_PATH, encoding="utf-8"))
    for k, v in V2.items():
        ALL.setdefault(k, v)      # 第一版優先
