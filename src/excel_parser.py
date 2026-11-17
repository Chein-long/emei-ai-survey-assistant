
from pathlib import Path
import re
import pandas as pd


# ==========================================
# 1. 设置项目路径
# ==========================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

INPUT_FILE = PROJECT_ROOT / "data" / "raw" / "采样表.xlsx"

OUTPUT_DIR = PROJECT_ROOT / "data" / "processed"

OUTPUT_FILE = OUTPUT_DIR / "MC-1_标准化数据.xlsx"


# ==========================================
# 2. 已经由用户确认的人工修正规则
# ==========================================

MANUAL_CORRECTIONS = {
    "MC-1-32": {
        "expected_raw_dbh_cm": 2345.0,
        "corrected_dbh_cm": 23.45,
        "reason": "用户确认：原始胸径2345为小数点录入错误，正确值为23.45 cm。"
    }
}


# ==========================================
# 3. 获取一列中的第一个非空值
# ==========================================

def first_non_empty(series):

    values = series.dropna()

    return values.iloc[0] if not values.empty else None


# ==========================================
# 4. 解析样地面积
# 例如：20m×20m
# ==========================================

def parse_plot_area(value):

    if pd.isna(value):
        return None, None, None

    text = str(value).replace(" ", "").lower()

    match = re.fullmatch(
        r"(\d+(?:\.\d+)?)m?[×x*](\d+(?:\.\d+)?)m?",
        text
    )

    if not match:
        return None, None, None

    length = float(match.group(1))
    width = float(match.group(2))

    return length, width, length * width


# ==========================================
# 5. 解析冠幅
# 第一个数字：东西冠幅
# 第二个数字：南北冠幅
# ==========================================

def parse_crown(value):

    if pd.isna(value):
        return None, None, "缺失"

    text = str(value).strip()

    match = re.fullmatch(
        r"(\d+(?:\.\d+)?)\s*\+\s*(\d+(?:\.\d+)?)",
        text
    )

    if not match:
        return None, None, "格式无法识别"

    east_west = float(match.group(1))
    north_south = float(match.group(2))

    return east_west, north_south, "成功"


# ==========================================
# 6. 主程序
# ==========================================

def main(input_file=INPUT_FILE, output_file=OUTPUT_FILE, *, single_plot=False):

    # 检查原始文件是否存在

    if not input_file.exists():

        raise FileNotFoundError(
            f"没有找到采样表：{input_file}"
        )

    # 读取Excel中的所有工作表
    # 只读取A-K列，避免读取多余空白列

    all_sheets = pd.read_excel(
        input_file,
        sheet_name=None,
        usecols="A:K"
    )

    # 自动跳过空工作表

    valid_sheets = [
        (name, frame.dropna(how="all"))
        for name, frame in all_sheets.items()
        if not frame.dropna(how="all").empty
    ]

    if not valid_sheets:
        raise ValueError("Excel中没有有效数据")

    if single_plot and len(valid_sheets) != 1:
        raise ValueError("请上传只含一个非空样地工作表的 Excel。")

    # 选择第一个非空工作表

    source_sheet, raw_df = valid_sheets[0]

    raw_df.columns = [
        str(column).strip()
        for column in raw_df.columns
    ]

    # 检查必要字段

    required_columns = [
        "样地代号", "面积：", "森林类型：",
        "海拔：", "经度", "纬度",
        "编号", "植物名称", "树高（m）",
        "胸径（cm）", "冠幅（m）"
    ]

    missing = [
        col for col in required_columns
        if col not in raw_df.columns
    ]

    if missing:
        raise ValueError(
            "缺少必要字段：" + "、".join(missing)
        )

    if single_plot:
        plot_ids = raw_df["样地代号"].dropna().astype(str).str.strip()
        if plot_ids[plot_ids.ne("")].nunique() != 1:
            raise ValueError("采样表必须填写且只包含一个样地编号。")
        tree_fields = ["编号", "植物名称", "树高（m）", "胸径（cm）", "冠幅（m）"]
        if not raw_df[tree_fields].notna().any(axis=None):
            raise ValueError("采样表没有乔木记录。")

    # ======================================
    # 7. 提取样地基本信息
    # ======================================

    area_raw = first_non_empty(raw_df["面积："])

    length, width, area = parse_plot_area(area_raw)

    plot_data = {
        "plot_id": first_non_empty(raw_df["样地代号"]),
        "plot_area_raw": area_raw,
        "plot_length_m": length,
        "plot_width_m": width,
        "plot_area_m2": area,
        "forest_type": first_non_empty(raw_df["森林类型："]),
        "elevation_m": first_non_empty(raw_df["海拔："]),
        "longitude": first_non_empty(raw_df["经度"]),
        "latitude": first_non_empty(raw_df["纬度"])
    }

    # ======================================
    # 8. 提取乔木调查数据
    # ======================================

    tree_raw = raw_df[
        ["编号", "植物名称", "树高（m）",
         "胸径（cm）", "冠幅（m）"]
    ].copy()

    if single_plot:
        tree_raw = tree_raw.dropna(how="all").copy()
    else:
        tree_raw = tree_raw.dropna(subset=["编号"]).copy()

    trees = pd.DataFrame({

        "tree_id": tree_raw["编号"].astype("string").str.strip(),

        "species": tree_raw["植物名称"].astype("string").str.strip(),

        "height_m": pd.to_numeric(
            tree_raw["树高（m）"],
            errors="coerce"
        ),

        "dbh_raw_cm": pd.to_numeric(
            tree_raw["胸径（cm）"],
            errors="coerce"
        ),

        "crown_raw": tree_raw["冠幅（m）"].astype("string").str.strip()

    })

    # 保留原始胸径，另设一个用于计算的胸径字段

    trees["dbh_cm"] = trees["dbh_raw_cm"]

    trees["correction_status"] = "未修改"

    trees["correction_reason"] = ""

    # ======================================
    # 9. 拆分冠幅
    # ======================================

    crown_results = trees["crown_raw"].apply(
        parse_crown
    )

    crown_df = pd.DataFrame(
        crown_results.tolist(),
        columns=[
            "crown_ew_m",
            "crown_ns_m",
            "crown_parse_status"
        ],
        index=trees.index
    )

    trees = pd.concat(
        [trees, crown_df],
        axis=1
    )

    # ======================================
    # 10. 应用人工确认的胸径修正
    # ======================================

    # 这条历史修正只适用于 MC-1 的已确认原始值。
    corrections = MANUAL_CORRECTIONS if str(plot_data["plot_id"]).strip() == "MC-1" else {}
    for tree_id, correction in corrections.items():

        matched = trees.index[
            trees["tree_id"] == tree_id
        ].tolist()

        if len(matched) != 1:
            continue

        idx = matched[0]
        original_value = trees.at[idx, "dbh_raw_cm"]

        if pd.isna(original_value) or original_value != correction["expected_raw_dbh_cm"]:
            continue

        trees.at[idx, "dbh_cm"] = (
            correction["corrected_dbh_cm"]
        )

        trees.at[idx, "correction_status"] = "人工确认修正"

        trees.at[idx, "correction_reason"] = (
            correction["reason"]
        )

    # ======================================
    # 11. 生成数据解析报告
    # ======================================

    report = pd.DataFrame([

        ["来源工作表", source_sheet],

        ["样地编号", plot_data["plot_id"]],

        ["乔木记录数量", len(trees)],

        [
            "冠幅解析成功数量",
            int((trees["crown_parse_status"] == "成功").sum())
        ],

        [
            "冠幅解析失败数量",
            int((trees["crown_parse_status"] != "成功").sum())
        ],

        [
            "人工确认修正数量",
            int((trees["correction_status"] == "人工确认修正").sum())
        ],

        [
            "重复树木编号数量",
            int(trees["tree_id"].duplicated().sum())
        ],

        [
            "树高缺失数量",
            int(trees["height_m"].isna().sum())
        ],

        [
            "胸径缺失数量",
            int(trees["dbh_cm"].isna().sum())
        ]

    ], columns=["检查项目", "检查结果"])

    # ======================================
    # 12. 导出标准化Excel
    # ======================================

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with pd.ExcelWriter(
        output_file,
        engine="openpyxl"
    ) as writer:

        pd.DataFrame([plot_data]).to_excel(
            writer,
            sheet_name="Plot",
            index=False
        )

        trees.to_excel(
            writer,
            sheet_name="Trees",
            index=False
        )

        report.to_excel(
            writer,
            sheet_name="Parse_Report",
            index=False
        )

    # ======================================
    # 13. 显示运行结果
    # ======================================

    print("\n========== Excel解析完成 ==========")

    print("原始文件：", input_file.name)

    print("来源工作表：", source_sheet)

    print("样地编号：", plot_data["plot_id"])

    print("样地面积：", plot_data["plot_area_m2"], "m²")

    print("乔木记录：", len(trees), "株")

    print(
        "冠幅解析成功：",
        int((trees["crown_parse_status"] == "成功").sum()),
        "株"
    )

    print(
        "人工确认修正：",
        int((trees["correction_status"] == "人工确认修正").sum()),
        "株"
    )

    print("\n人工修正记录：")

    print(
        trees.loc[
            trees["correction_status"] == "人工确认修正",
            [
                "tree_id",
                "dbh_raw_cm",
                "dbh_cm",
                "correction_status"
            ]
        ].to_string(index=False)
    )

    print("\n标准化结果已保存至：")

    print(output_file)


if __name__ == "__main__":
    main()
